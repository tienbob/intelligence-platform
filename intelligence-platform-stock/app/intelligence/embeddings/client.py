"""
Embedding provider client — provider abstraction with retry/backoff.

Owns everything about talking to an embedding provider:

- lazy client initialization
- provider validation
- single/batch calls
- blank-input handling
- retry with exponential backoff on transient failures

Knows nothing about domains or persistence.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_PROVIDERS = frozenset({"openai", "gemini"})


class EmbeddingClient:
    """
    Provider-agnostic embedding client.

    Usage:

        client = EmbeddingClient()

        vector = await client.embed(
            "Apple Inc. is a technology company"
        )

        vectors = await client.embed_batch(
            ["text one", "text two"]
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        dimensions: int | None = None,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.5,
    ):
        settings = get_settings()

        self.api_key = api_key or settings.EMBEDDING_API_KEY
        self.model = model or settings.EMBEDDING_MODEL
        self.provider = provider or settings.EMBEDDING_PROVIDER
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS

        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

        self._client: Any = None

    # ── Configuration ───────────────────────────────────────────

    async def _get_client(self) -> Any:
        """
        Lazily initialize the provider SDK client.

        google-genai's async surface is:
            genai.Client(...).aio
        """

        if self._client is None:
            self.validate_config(require_api_key=True)

            if self.provider == "openai":
                import openai

                self._client = openai.AsyncOpenAI(
                    api_key=self.api_key,
                )

            elif self.provider == "gemini":
                from google import genai

                self._client = genai.Client(
                    api_key=self.api_key,
                )

        return self._client

    # ── Error classification ────────────────────────────────────

    @staticmethod
    def _is_rate_limit_error(exc: BaseException) -> bool:
        """
        Detect provider rate-limit / quota-exhaustion errors.

        Gemini exposes quota exhaustion as a ClientError with code 429.
        Other providers may expose status_code/status/response.status_code.
        """

        code = getattr(exc, "code", None)
        if code == 429 or str(code) == "429":
            return True

        status_code = getattr(exc, "status_code", None)
        if status_code == 429 or str(status_code) == "429":
            return True

        status = getattr(exc, "status", None)
        if status == 429 or str(status) == "429":
            return True

        response = getattr(exc, "response", None)
        response_status = getattr(response, "status_code", None)

        if response_status == 429 or str(response_status) == "429":
            return True

        message = str(exc).lower()

        rate_limit_markers = (
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "too many requests",
            "quota exceeded",
            "quota_exceeded",
            "429",
        )

        return any(marker in message for marker in rate_limit_markers)

    @staticmethod
    def _extract_retry_delay(exc: BaseException) -> float | None:
        """
        Extract a provider-supplied retry delay when available.

        Google Gemini commonly returns:

            retryDelay: "59s"

        This method intentionally remains provider-independent.
        """

        # Some SDKs expose retry-after directly.
        for attribute in (
            "retry_after",
            "retry_after_seconds",
            "retry_delay",
        ):
            value = getattr(exc, attribute, None)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                pass

        # Inspect common string representations such as:
        #
        #   retryDelay: '59s'
        #   retryDelay: "59s"
        #
        message = str(exc)

        import re

        match = re.search(
            r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s",
            message,
            flags=re.IGNORECASE,
        )

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    # ── Retry plumbing ──────────────────────────────────────────

    async def _with_retries(self, call):
      """
      Run an async provider call with bounded retries.

      Provider SDKs such as google-genai already implement their own
      retry behavior for rate limits. We therefore propagate 429 quota
      errors immediately instead of adding another retry layer.
      """

      attempts = self.max_retries + 1

      for attempt in range(attempts):
          try:
              return await call()

          except Exception as exc:
              if self._is_rate_limit_error(exc):
                  logger.warning(
                      "Embedding provider quota/rate limit exhausted; "
                      "propagating without additional retry."
                  )
                  raise

              if attempt >= attempts - 1:
                  raise

              delay = self.retry_backoff_seconds * (2**attempt)

              logger.warning(
                  "Embedding call failed (attempt %d/%d); "
                  "retrying in %.1fs",
                  attempt + 1,
                  attempts,
                  delay,
              )

              await asyncio.sleep(delay)

    # ── Provider calls ──────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text.

        Blank input returns an empty vector.
        """

        if not text or not text.strip():
            return []

        client = await self._get_client()

        async def _call():
            if self.provider == "openai":
                response = await client.embeddings.create(
                    input=text,
                    model=self.model,
                )

                return response.data[0].embedding

            result = await client.aio.models.embed_content(
                model=self.model,
                contents=text,
            )

            if not result.embeddings:
                return []

            return result.embeddings[0].values or []

        vector = await self._with_retries(_call)

        return list(vector)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Blank strings are never sent to the provider but retain their
        positional slots as empty vectors.

        Provider quota/rate-limit errors are propagated to the caller.
        """

        if not texts:
            return []

        if all(not text or not text.strip() for text in texts):
            return [[] for _ in texts]

        non_blank_indices = [
            i
            for i, text in enumerate(texts)
            if text and text.strip()
        ]

        non_blank_texts = [
            texts[i]
            for i in non_blank_indices
        ]

        client = await self._get_client()

        async def _call():
            if self.provider == "openai":
                response = await client.embeddings.create(
                    input=non_blank_texts,
                    model=self.model,
                )

                return [
                    item.embedding
                    for item in response.data
                ]

            result = await client.aio.models.embed_content(
                model=self.model,
                contents=non_blank_texts,
            )

            embeddings = result.embeddings or []

            return [
                embedding.values or []
                for embedding in embeddings
            ]

        non_blank_vectors = await self._with_retries(_call)

        if len(non_blank_vectors) != len(non_blank_texts):
            raise ValueError(
                "Embedding provider returned "
                f"{len(non_blank_vectors)} vectors for "
                f"{len(non_blank_texts)} non-blank inputs"
            )

        vectors: list[list[float]] = [
            []
            for _ in texts
        ]

        for idx, vector in zip(
            non_blank_indices,
            non_blank_vectors,
        ):
            vectors[idx] = vector

        return vectors

    # ── Validation ──────────────────────────────────────────────

    def validate_config(
        self,
        require_api_key: bool = False,
    ) -> None:
        """
        Validate provider configuration with clear, actionable errors.
        """

        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding provider: {self.provider!r}. "
                f"Supported providers: {sorted(SUPPORTED_PROVIDERS)}. "
                "Set EMBEDDING_PROVIDER in your environment / .env."
            )

        if require_api_key and not self.api_key:
            raise ValueError(
                f"EMBEDDING_API_KEY is required for provider "
                f"{self.provider!r} but is not set. "
                "Add EMBEDDING_API_KEY to your environment / .env."
            )