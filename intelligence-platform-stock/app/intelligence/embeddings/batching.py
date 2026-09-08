"""
Batch embedding orchestration — batch-first with per-item fallback.

Owns the generic batching policy:

    1. Try one provider call for the whole batch.
    2. If the batch call fails with a quota/rate-limit error, split the
       chunk recursively (halving down to per-item) with a short backoff
       between retries. Many providers reject large single requests but
       accept smaller ones, and splitting avoids discarding the entire
       batch for a transient 429.
    3. For other batch failures, fall back to per-item calls.
    4. Isolate per-item failures so one bad item never aborts the batch.

Only when even a 1-item shard is rejected by the provider is the
rate-limit error propagated (the quota is genuinely exhausted).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core.logging import get_logger
from app.intelligence.embeddings.types import chunked

logger = get_logger(__name__)

T = TypeVar("T")

# item -> vector; returns [] when the item could not be embedded.
SingleEmbedFn = Callable[[T], Awaitable[list[float]]]

# items -> vectors; returned vectors must remain positionally aligned.
BatchEmbedFn = Callable[[list[T]], Awaitable[list[list[float]]]]


def _is_rate_limit_error(exc: BaseException) -> bool:
    """
    Detect provider rate-limit / quota-exhaustion errors without coupling
    the generic batching layer to a specific provider SDK.

    Google Gemini:
        google.genai.errors.ClientError
        code == 429

    Other providers may expose:
        status_code == 429
        status == 429
        HTTP-style response.status_code == 429

    We also inspect common textual representations as a final fallback.
    """

    # Google / generic SDKs often expose ``code``.
    code = getattr(exc, "code", None)
    if code == 429 or str(code) == "429":
        return True

    # Some clients expose ``status_code`` directly.
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or str(status_code) == "429":
        return True

    # Some exception objects expose ``status``.
    status = getattr(exc, "status", None)
    if status == 429 or str(status) == "429":
        return True

    # Some HTTP client exceptions expose response.status_code.
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status == 429 or str(response_status) == "429":
        return True

    # Last-resort provider-independent detection.
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


async def embed_batch_with_fallback(
    items: list[T],
    *,
    embed_one: SingleEmbedFn,
    embed_many: BatchEmbedFn,
    chunk_size: int = 100,
    max_rate_limit_split_depth: int = 6,
    rate_limit_retry_backoff: float = 3.0,
) -> list[list[float]]:
    """
    Embed ``items`` in chunks with a single provider call per chunk.

    Normal batch failures:
        Fall back to per-item embedding.

    Rate-limit / quota failures:
        Recursively split the chunk in half (down to single items) with a
        short backoff between retries. Many providers rate-limit large
        single requests (per-request / per-token quotas) but accept smaller
        requests. Splitting lets bulk ingestion make forward progress
        instead of discarding the entire batch.

        If every shard still fails at size 1, propagate the rate-limit
        error so the policy boundary stays explicit.

    Other per-item failures:
        Are isolated and represented by an empty vector.

    The returned list is positionally aligned with ``items``.
    """

    async def embed_shard(
        shard: list[T],
        *,
        depth: int,
    ) -> list[list[float]]:
        """Embed one shard; on rate-limit error, split recursively."""
        if not shard:
            return []

        try:
            shard_vectors = await embed_many(shard)

            if len(shard_vectors) != len(shard):
                raise ValueError(
                    f"embed_many returned {len(shard_vectors)} vectors "
                    f"for {len(shard)} items"
                )

            return shard_vectors

        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise

            if depth <= 0 or len(shard) <= 1:
                logger.error(
                    (
                        "Embedding shard of %d item(s) rejected by provider "
                        "rate limit/quota after splitting; propagating."
                    ),
                    len(shard),
                )
                raise

            logger.warning(
                (
                    "Rate limit/quota on %d-item shard; splitting into two "
                    "halves and retrying (depth=%d)."
                ),
                len(shard),
                depth,
            )

            await asyncio.sleep(rate_limit_retry_backoff)

            mid = len(shard) // 2

            left = await embed_shard(
                shard[:mid],
                depth=depth - 1,
            )
            right = await embed_shard(
                shard[mid:],
                depth=depth - 1,
            )
            return left + right

    if not items:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    vectors: list[list[float]] = [[] for _ in items]

    offset = 0

    for chunk in chunked(items, chunk_size):
        try:
            chunk_vectors = await embed_many(chunk)

            if len(chunk_vectors) != len(chunk):
                raise ValueError(
                    f"embed_many returned {len(chunk_vectors)} vectors "
                    f"for {len(chunk)} items"
                )

            vectors[offset : offset + len(chunk)] = chunk_vectors

        except Exception as exc:
            # Rate-limit/quota: split the chunk recursively instead of
            # brute-forcing per-item requests, and instead of discarding the
            # whole batch (which previously left filings permanently
            # unembedded).
            if _is_rate_limit_error(exc):
                logger.warning(
                    (
                        "Batch embedding rate-limited at item range "
                        "%d-%d; recursively splitting until the provider "
                        "accepts the shards."
                    ),
                    offset,
                    offset + len(chunk) - 1,
                )

                shard_vectors = await embed_shard(
                    chunk,
                    depth=max(1, max_rate_limit_split_depth),
                )
                vectors[offset : offset + len(chunk)] = shard_vectors

                offset += len(chunk)
                continue

            logger.exception(
                (
                    "Batch embedding failed for items %d-%d; "
                    "falling back to per-item embedding"
                ),
                offset,
                offset + len(chunk) - 1,
            )

            for i, item in enumerate(chunk):
                absolute_index = offset + i

                try:
                    vectors[absolute_index] = await embed_one(item)

                except Exception as item_exc:
                    # A rate-limit can also appear during an individual
                    # fallback request. Once that happens, stop immediately
                    # rather than continuing to consume quota.
                    if _is_rate_limit_error(item_exc):
                        logger.error(
                            (
                                "Per-item embedding hit provider "
                                "rate limit/quota at index %d; "
                                "stopping fallback."
                            ),
                            absolute_index,
                        )
                        raise

                    logger.exception(
                        "Embedding failed for item at index %d",
                        absolute_index,
                    )

        offset += len(chunk)

    return vectors