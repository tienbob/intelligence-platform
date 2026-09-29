"""
LLM client — generic OpenAI-compatible transport engine.

Owns the HOW of model interaction: client construction, chat-completions
call with JSON mode, retry/timeout configuration, token accounting, and
robust response parsing. Domains supply WHAT to ask (prompt, context,
schema validation).
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from app.core.logging import get_logger
from app.intelligence.llm.structured_output import extract_json

logger = get_logger(__name__)

# Sentinel returned by classify_llm_error: the model is rate-limited by a
# per-DAY quota (e.g. Gemini free tier: 20 requests/day/model). Retrying the
# same model cannot succeed until the quota resets — the only useful move is
# failing over to another model immediately.
DAILY_QUOTA = -2.0


def classify_llm_error(exc: Exception) -> float | None:
    """
    Classify a provider error for retryability.

    Returns:
        ``None``  — non-transient (auth, bad request, model not found, …).
                    Retrying cannot succeed; raise to the caller.
        ``-1.0``  — transient (429 rate limit, 5xx including 503 "model is
                    experiencing high demand", timeouts, connection blips)
                    with no server-supplied wait hint.
        ``>= 0``  — transient and the server asked us to wait this many
                    seconds (``Retry-After`` header).
    """
    try:
        import openai
    except ImportError:  # pragma: no cover — openai is a hard dependency
        return None
    transient = (
        openai.RateLimitError,
        openai.InternalServerError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    )
    if not isinstance(exc, transient):
        return None
    # Per-day quota exhaustion (e.g. Gemini free tier —
    # "GenerateRequestsPerDayPerProjectPerModel-FreeTier"): retrying the
    # same model is pointless; fail over to the fallback model immediately.
    msg = str(exc).lower()
    if isinstance(exc, openai.RateLimitError) and (
        "free_tier" in msg or "perday" in msg or "per day" in msg
    ):
        return DAILY_QUOTA
    retry_after: float = -1.0
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        try:
            retry_after = max(0.0, float(headers.get("retry-after")))
        except (TypeError, ValueError):
            retry_after = -1.0
    return retry_after


class LLMClient:
    """
    OpenAI-API-compatible LLM client.

    Works against any provider exposing an OpenAI-compatible
    ``/v1/chat/completions`` endpoint (OpenAI, Gemini, Azure, Ollama, vLLM)
    by pointing ``base_url`` at it.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        base_url: str | None = None,
        provider: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        sdk_max_retries: int = 1,
        max_attempts: int = 4,
        retry_base_delay: float = 5.0,
        retry_max_delay: float = 60.0,
        fallback_model: str | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or None
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.sdk_max_retries = sdk_max_retries
        # App-level retry policy for transient provider errors (see
        # _create_with_retry). Total attempts = max_attempts per model.
        self.max_attempts = max(1, max_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        # Used only when the primary model exhausts retries on a transient
        # error (e.g. demand-spike 503s on a hot model).
        self.fallback_model = fallback_model
        # Model that actually produced the last successful response —
        # build_meta reports this so provenance survives fallbacks.
        self.last_model_used: str | None = None
        self._client: Any = None

    async def get_client(self) -> Any:
        """Get the OpenAI-compatible client (lazy init)."""
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                # Fail fast on unreachable providers instead of leaving
                # analysis jobs stuck waiting forever.
                timeout=self.timeout,
                max_retries=self.sdk_max_retries,
            )
        return self._client

    def build_user_message(
        self, context: dict[str, Any], user_query: str | None = None
    ) -> str:
        """Serialize structured context into the user message."""
        context_json = json.dumps(context, indent=2, default=str)
        return (
            user_query
            or f"Analyze the following data and provide a structured analysis.\n\nContext:\n{context_json}"
        )

    async def chat_json(
        self, system_prompt: str, user_message: str
    ) -> tuple[dict[str, Any], int | None]:
        """
        Run a JSON-mode chat completion and parse the response.

        Returns ``(parsed_result, tokens_used)``. Invalid JSON is recovered
        via :func:`extract_json` rather than raising, mirroring production
        behavior. Transient provider errors (rate limits, 503 demand
        spikes, timeouts) are retried with backoff — see
        :meth:`_create_with_retry`.
        """
        client = await self.get_client()

        response = await self._create_with_retry(client, system_prompt, user_message)
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else None

        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error("LLM returned invalid JSON, attempting extraction")
            result = extract_json(content)

        return result, tokens_used

    async def _create_with_retry(
        self, client: Any, system_prompt: str, user_message: str
    ) -> Any:
        """
        ``chat.completions.create`` with application-level backoff + fallback.

        The SDK retries connection errors internally (``sdk_max_retries``,
        short fixed delay), but provider demand spikes like 503 "This model
        is currently experiencing high demand" can outlast it — and, as seen
        live, can even outlast a full backoff loop on a hot model. So:

        1. Retry the primary model with exponential backoff + jitter,
           honoring server ``Retry-After`` when present.
        2. If the primary exhausts its retries on a **transient** error and a
           ``fallback_model`` is configured, run the same loop against the
           fallback model before giving up.

        Non-transient errors (auth, bad request, model not found) raise
        immediately: retrying cannot succeed, and falling back would only
        mask a configuration problem.
        """
        try:
            return await self._attempt_loop(client, self.model, system_prompt, user_message)
        except Exception as exc:
            if (
                not self.fallback_model
                or self.fallback_model == self.model
                or classify_llm_error(exc) is None
            ):
                raise
            logger.warning(
                "Primary model %s unavailable after %d attempts (%s) — retrying with fallback model %s",
                self.model,
                self.max_attempts,
                exc,
                self.fallback_model,
            )
        return await self._attempt_loop(
            client, self.fallback_model, system_prompt, user_message
        )

    async def _attempt_loop(
        self, client: Any, model: str, system_prompt: str, user_message: str
    ) -> Any:
        """One model's attempt loop: exponential backoff + jitter."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                )
                self.last_model_used = model
                return response
            except Exception as exc:
                retry_after = classify_llm_error(exc)
                # Daily-quota exhaustion (DAILY_QUOTA) raises immediately:
                # retrying the same model cannot succeed today.
                if (
                    retry_after is None
                    or retry_after == DAILY_QUOTA
                    or attempt >= self.max_attempts
                ):
                    raise
                if retry_after >= 0:
                    delay = min(retry_after, self.retry_max_delay)
                else:
                    delay = min(
                        self.retry_base_delay * (2 ** (attempt - 1)),
                        self.retry_max_delay,
                    )
                delay += random.uniform(0, 1)  # jitter: avoid thundering herds
                logger.warning(
                    "Transient LLM provider error (attempt %d/%d, model %s) — retrying in %.1fs: %s",
                    attempt,
                    self.max_attempts,
                    model,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover

    def build_meta(
        self,
        *,
        tokens_used: int | None,
        prompt_name: str | None,
        prompt_version: str,
        analysis_type: str,
    ) -> dict[str, Any]:
        """Assemble the standard ``_meta`` audit block."""
        return {
            "model": self.last_model_used or self.model,
            "provider": self.provider,
            "tokens_used": tokens_used,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "analysis_type": analysis_type,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }