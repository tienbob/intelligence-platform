"""
Generic embedding service — generation, batching, and persistence.

This service owns the generic mechanics of:

    - embedding text through EmbeddingClient
    - batching provider requests
    - fallback embedding generation
    - assigning generated vectors to VectorRecord
    - persisting vectors through PgVectorStore
    - reporting successful / failed records

It knows nothing about domains.

Domain code is responsible for deciding:

    - which entities should be embedded
    - what content should be embedded
    - what metadata should be attached
    - which entity_type should be used
    - when ingestion should run

Persistence is framework-owned through:

    app.intelligence.models.embeddings.Embedding

Transaction ownership
---------------------
Single-record operations preserve the historical behavior of committing
through PgVectorStore.

Batch operations use PgVectorStore.store(..., commit=False) and commit the
whole batch once. This prevents one transaction per embedding and gives the
batch a predictable transaction boundary.

Failure handling
----------------
Provider failures are handled by embed_batch_with_fallback().

Persistence failures are NOT silently swallowed at the batch level.

A failed batch is rolled back and the exception is propagated to the caller.
This is intentional: an ingestion worker should know that indexing failed
rather than reporting a misleading partial success.

Per-record persistence isolation is still available through ``store_one`` for
callers that explicitly want partial success semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.intelligence.embeddings.batching import embed_batch_with_fallback
from app.intelligence.embeddings.client import EmbeddingClient
from app.intelligence.embeddings.persistence import PgVectorStore
from app.intelligence.embeddings.types import VectorRecord

logger = get_logger(__name__)

T = TypeVar("T")

StoreOne = Callable[
    [AsyncSession, VectorRecord, list[float]],
    Awaitable[bool],
]


class GenericEmbeddingService:
    """
    Domain-agnostic embedding engine.

    Example:

        svc = GenericEmbeddingService(
            store=PgVectorStore(),
        )

        vector = await svc.embed("some content")

        stored = await svc.store(session, record)

        count = await svc.embed_and_store_batch(
            session,
            records,
        )
    """

    def __init__(
        self,
        store: PgVectorStore | None = None,
        client: EmbeddingClient | None = None,
        *,
        batch_size: int = 100,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")

        self.client = client or EmbeddingClient()
        self.dimensions = self.client.dimensions
        self.store = store
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single piece of text.

        Blank-text behavior is delegated to EmbeddingClient.
        """
        if text is None:
            raise ValueError("Cannot embed None.")

        return await self.client.embed(text)

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """
        Embed multiple texts.

        The actual provider batching is delegated to EmbeddingClient.
        """
        if not texts:
            return []

        return await self.client.embed_batch(texts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _require_store(self) -> PgVectorStore:
        """
        Return the configured vector store or fail clearly.
        """
        if self.store is None:
            raise RuntimeError(
                "GenericEmbeddingService requires a vector store "
                "for persistence operations."
            )

        return self.store

    async def store(
        self,
        session: AsyncSession,
        record: VectorRecord,
        *,
        commit: bool = True,
    ) -> Any:
        """
        Persist an already-embedded record.

        The record model is automatically populated from the embedding client
        when it has not already been assigned.

        Args:
            session:
                Active AsyncSession.

            record:
                VectorRecord containing content and vector.

            commit:
                Whether PgVectorStore should commit immediately.

                True:
                    single-record / legacy behavior.

                False:
                    intended for batch transactions.
        """
        store = self._require_store()

        if record.model is None:
            record.model = self.client.model

        return await store.store(
            session,
            record,
            commit=commit,
        )

    async def embed_and_store(
        self,
        session: AsyncSession,
        record: VectorRecord,
    ) -> Any:
        """
        Embed ``record.content`` and persist the resulting vector.

        This is the single-record convenience path.
        """
        if not record.content or not record.content.strip():
            raise ValueError(
                f"Cannot embed empty content for "
                f"{record.entity_type}/{record.entity_id}."
            )

        record.vector = await self.embed(record.content)

        if not record.vector:
            raise ValueError(
                f"Embedding provider returned an empty vector for "
                f"{record.entity_type}/{record.entity_id}."
            )

        return await self.store(
            session,
            record,
            commit=True,
        )

    # ------------------------------------------------------------------
    # Batch persistence
    # ------------------------------------------------------------------

    async def embed_and_store_batch(
        self,
        session: AsyncSession,
        records: list[VectorRecord],
        *,
        store_one: StoreOne | None = None,
        atomic: bool = True,
    ) -> int:
        """
        Embed records in batches and persist them.

        Default behavior is atomic:

            1. Generate all vectors.
            2. Persist valid vectors.
            3. Commit once.
            4. Roll back the whole batch if persistence fails.

        This is the preferred ingestion-worker path.

        ``store_one`` can be supplied when a caller explicitly requires
        custom persistence semantics.

        When ``atomic=True`` and ``store_one`` is supplied, the callback is
        still expected to participate in the caller's transaction.

        Args:
            session:
                Active AsyncSession.

            records:
                VectorRecord objects containing content but normally no vector.

            store_one:
                Optional custom persistence callback:

                    async (session, record, vector) -> bool

            atomic:
                If True, persist the whole batch in one transaction.

        Returns:
            Number of successfully persisted records.

        Raises:
            RuntimeError:
                If no persistence store is configured and no custom callback
                is provided.

            Exception:
                Provider or persistence errors are propagated when atomic
                ingestion fails.
        """
        if not records:
            return 0

        if store_one is None:
            self._require_store()

        logger.info(
            "Embedding batch started: %d records, batch_size=%d, "
            "atomic=%s, model=%s, dimensions=%d",
            len(records),
            self._batch_size,
            atomic,
            self.client.model,
            self.dimensions,
        )

        # --------------------------------------------------------------
        # Validate records before spending provider calls.
        # --------------------------------------------------------------

        valid_records: list[VectorRecord] = []

        for record in records:
            if not record.content or not record.content.strip():
                logger.warning(
                    "Skipping empty embedding content for %s/%s",
                    record.entity_type,
                    record.entity_id,
                )
                continue

            if record.model is None:
                record.model = self.client.model

            valid_records.append(record)

        if not valid_records:
            logger.warning(
                "Embedding batch contained no valid records."
            )
            return 0

        # --------------------------------------------------------------
        # Generate embeddings.
        #
        # embed_batch_with_fallback handles provider batch failures by
        # falling back to individual embedding calls according to its
        # implementation.
        # --------------------------------------------------------------

        vectors = await embed_batch_with_fallback(
            [record.content for record in valid_records],
            embed_one=self.embed,
            embed_many=self.embed_batch,
            chunk_size=self._batch_size,
        )

        if len(vectors) != len(valid_records):
            raise RuntimeError(
                "Embedding provider returned an unexpected number of vectors: "
                f"expected {len(valid_records)}, got {len(vectors)}."
            )

        # --------------------------------------------------------------
        # Custom persistence path.
        #
        # This preserves the extension point from the original service.
        # --------------------------------------------------------------

        if store_one is not None:
            return await self._persist_with_callback(
                session,
                valid_records,
                vectors,
                store_one,
                atomic=atomic,
            )

        # --------------------------------------------------------------
        # Default PgVectorStore path.
        #
        # IMPORTANT:
        # Store with commit=False and commit once at the end.
        # --------------------------------------------------------------

        return await self._persist_batch(
            session,
            valid_records,
            vectors,
            atomic=atomic,
        )

    async def _persist_batch(
        self,
        session: AsyncSession,
        records: list[VectorRecord],
        vectors: list[list[float]],
        *,
        atomic: bool,
    ) -> int:
        """
        Persist using the configured PgVectorStore.
        """
        store = self._require_store()

        persisted = 0

        try:
            for record, vector in zip(records, vectors):
                if not vector:
                    logger.warning(
                        "Skipping %s/%s: empty embedding vector",
                        record.entity_type,
                        record.entity_id,
                    )
                    continue

                record.vector = vector

                await store.store(
                    session,
                    record,
                    commit=False,
                )

                persisted += 1

            if atomic:
                from app.core.database import commit_session

                await commit_session(session)

            else:
                # ``atomic=False`` means the caller owns the transaction.
                # We still flush so database errors are surfaced now.
                await session.flush()

            logger.info(
                "Embedding batch persisted: %d/%d records",
                persisted,
                len(records),
            )

            return persisted

        except Exception:
            await session.rollback()

            logger.exception(
                "Embedding batch persistence failed; "
                "transaction rolled back"
            )

            raise

    async def _persist_with_callback(
        self,
        session: AsyncSession,
        records: list[VectorRecord],
        vectors: list[list[float]],
        store_one: StoreOne,
        *,
        atomic: bool,
    ) -> int:
        """
        Persist through a caller-supplied callback.

        Atomic mode propagates the first failure and rolls back.

        Non-atomic mode isolates failures per record and continues.
        """
        from app.core.database import commit_session

        count = 0

        if atomic:
            try:
                for record, vector in zip(records, vectors):
                    if not vector:
                        logger.warning(
                            "Skipping %s/%s: empty embedding vector",
                            record.entity_type,
                            record.entity_id,
                        )
                        continue

                    record.vector = vector

                    stored = await store_one(
                        session,
                        record,
                        vector,
                    )

                    if stored:
                        count += 1

                await commit_session(session)

                logger.info(
                    "Custom embedding batch persisted: %d/%d records",
                    count,
                    len(records),
                )

                return count

            except Exception:
                await session.rollback()

                logger.exception(
                    "Custom embedding batch failed; "
                    "transaction rolled back"
                )

                raise

        # --------------------------------------------------------------
        # Explicit partial-success mode.
        # --------------------------------------------------------------

        for record, vector in zip(records, vectors):
            if not vector:
                logger.warning(
                    "Skipping %s/%s: empty embedding vector",
                    record.entity_type,
                    record.entity_id,
                )
                continue

            try:
                record.vector = vector

                stored = await store_one(
                    session,
                    record,
                    vector,
                )

                if stored:
                    count += 1

            except Exception:
                await session.rollback()

                logger.exception(
                    "Failed to store embedding for %s/%s; "
                    "continuing with remaining records",
                    record.entity_type,
                    record.entity_id,
                )

        return count

    # ------------------------------------------------------------------
    # Default callback compatibility
    # ------------------------------------------------------------------

    async def _default_store_one(
        self,
        session: AsyncSession,
        record: VectorRecord,
        vector: list[float],
    ) -> bool:
        """
        Default callback-compatible persistence method.

        Uses the vector store without committing. The caller owns the
        transaction.
        """
        if not vector:
            logger.warning(
                "Skipping %s/%s: empty embedding vector",
                record.entity_type,
                record.entity_id,
            )
            return False

        record.vector = vector

        await self.store(
            session,
            record,
            commit=False,
        )

        return True


def build_generic_service(
    embedding_model: type | None = None,
    *,
    dimensions: int | None = None,
    model_name: str | None = None,
    client: EmbeddingClient | None = None,
) -> GenericEmbeddingService:
    """
    Convenience factory for the generic embedding service.

    The default persistence model is the framework-owned Embedding ORM.

    ``embedding_model`` exists for dependency injection/testing symmetry.
    Passing a model does not transfer architectural ownership of the
    embeddings schema to a domain.
    """
    resolved_client = client or EmbeddingClient()

    resolved_dimensions = (
        dimensions
        if dimensions is not None
        else resolved_client.dimensions
    )

    resolved_model_name = (
        model_name
        if model_name is not None
        else resolved_client.model
    )

    store = PgVectorStore(
        model=embedding_model,
        dimensions=resolved_dimensions,
        default_model_name=resolved_model_name,
    )

    return GenericEmbeddingService(
        store=store,
        client=resolved_client,
    )
