"""
Batch embedding orchestration — batch-first with per-item fallback.

Owns the generic batching policy:
    1. Try one provider call for the whole batch.
    2. If the batch call fails, fall back to per-item calls.
    3. Isolate per-item failures so one bad item never aborts the batch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.logging import get_logger
from app.intelligence.embeddings.types import chunked

logger = get_logger(__name__)

T = TypeVar("T")

# item -> vector ; returns [] (empty) when the item could not be embedded
SingleEmbedFn = Callable[[T], Awaitable[list[float]]]
BatchEmbedFn = Callable[[list[T]], Awaitable[list[list[float]]]]


async def embed_batch_with_fallback(
    items: list[T],
    *,
    embed_one: SingleEmbedFn,
    embed_many: BatchEmbedFn,
    chunk_size: int = 100,
) -> list[list[float]]:
    """
    Embed ``items`` in chunks with a single call per chunk.

    On chunk failure, falls back to per-item embedding and isolates
    errors (failed items yield empty vectors). The returned list is
    positionally aligned with ``items``.
    """
    if not items:
        return []

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
        except Exception:
            logger.exception("Batch embedding failed; falling back to per-item")
            for i, item in enumerate(chunk):
                try:
                    vectors[offset + i] = await embed_one(item)
                except Exception:
                    logger.exception("Embedding failed for item at index %d", offset + i)
        offset += len(chunk)
    return vectors