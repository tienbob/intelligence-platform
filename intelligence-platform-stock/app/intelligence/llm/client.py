"""
LLM client — generic OpenAI-compatible transport engine.

Owns the HOW of model interaction: client construction, chat-completions
call with JSON mode, retry/timeout configuration, token accounting, and
robust response parsing. Domains supply WHAT to ask (prompt, context,
schema validation).
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.intelligence.llm.structured_output import extract_json

logger = get_logger(__name__)


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
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or None
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.sdk_max_retries = sdk_max_retries
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
        behavior.
        """
        client = await self.get_client()

        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else None

        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error("LLM returned invalid JSON, attempting extraction")
            result = extract_json(content)

        return result, tokens_used

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
            "model": self.model,
            "provider": self.provider,
            "tokens_used": tokens_used,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "analysis_type": analysis_type,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }