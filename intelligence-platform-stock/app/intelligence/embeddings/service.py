"""
Generic embedding service — orchestrates client, batching, and persistence.

Knows HOW to produce and store embeddings end-to-end. Knows nothing about
domains: which content to embed, what metadata to attach, and when to run
are domain decisions.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.intelligence.embeddings.batching import embed_batch_with_fallback
from app.intelligence.embeddings.client import EmbeddingClient
from app.intelligence.embeddings.persistence import PgVectorStore
from app.intelligence.embeddings.types import VectorRecord

logger = get_logger(__name__)

T = TypeVar("T")


class GenericEmbeddingService:
    """
    Domain-agnostic embedding engine.

    Usage:
        svc = GenericEmbeddingService(
            store=PgVectorStore(MyDomainEmbeddingModel, 1536, "text-embedding-3-small"),
        )
        vector = await svc.embed("some content")
        stored = await svc.store(session, record)
        count = await svc.embed_and_store_batch(session, records)
    """

    def __init__(
        self,
        store: PgVectorStore | None = None,
        client: EmbeddingClient | None = None,
        *,
        batch_size: int = 100,
    ):
        self.client = client or EmbeddingClient()
        self.dimensions = self.client.dimensions
        self.store = store
        self._batch_size = batch_size

    # ── Generation ──────────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Embed a single text (blank → empty vector)."""
        return await self.client.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one provider call per chunk."""
        return await self.client.embed_batch(texts)

    # ── Persistence ─────────────────────────────────────────────

    async def store(self, session: AsyncSession, record: VectorRecord) -> Any:
        """Persist an embedded record via the configured vector store."""
        if self.store is None:
            raise RuntimeError("GenericEmbeddingService requires a vector store")
        if record.model is None:
            record.model = self.client.model
        return await self.store.store(session, record)

    async def embed_and_store(
        self,
        session: AsyncSession,
        record: VectorRecord,
    ) -> Any:
        """Embed ``record.content`` then persist it."""
        record.vector = await self.embed(record.content)
        return await self.store(session, record)

    async def embed_and_store_batch(
        self,
        session: AsyncSession,
        records: list[VectorRecord],
        *,
        store_one: Any | None = None,
    ) -> int:
        """
        Batch-embed records then persist each with per-item error isolation.

        ``store_one`` lets the caller customize persistence per record
        (async callable ``(session, record, vector) -> bool``); defaults
        to the configured vector store. Returns the number of rows
        persisted.
        """
        if not records:
            return 0

        persist = store_one or self._default_store_one

        vectors = await embed_batch_with_fallback(
            [r.content for r in records],
            embed_one=self.embed,
            embed_many=self.embed_batch,
            chunk_size=self._batch_size,
        )

        count = 0
        for record, vector in zip(records, vectors):
            try:
                if await persist(session, record, vector):
                    count += 1
            except Exception:
                logger.exception(
                    "Failed to store embedding for %s/%s",
                    record.entity_type,
                    record.entity_id,
                )
        return count

    async def _default_store_one(
        self,
        session: AsyncSession,
        record: VectorRecord,
        vector: list[float],
    ) -> bool:
        if not vector:
            logger.warning(
                "Skipping %s/%s: empty embedding vector",
                record.entity_type,
                record.entity_id,
            )
            return False
        record.vector = vector
        await self.store(session, record)
        return True


def build_generic_service(
    embedding_model: type,
    *,
    dimensions: int | None = None,
    model_name: str | None = None,
    client: EmbeddingClient | None = None,
) -> GenericEmbeddingService:
    """
    Convenience factory binding a domain's embedding ORM table to a
    generic service. Each domain passes its own table class.
    """
    resolved_client = client or EmbeddingClient()
    store = PgVectorStore(
        embedding_model,
        dimensions or resolved_client.dimensions,
        model_name or resolved_client.model,
    )
    return GenericEmbeddingService(store=store, client=resolved_client)