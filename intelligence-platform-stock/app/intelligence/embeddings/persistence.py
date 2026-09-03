"""
pgvector persistence + duplicate detection.

Owns the generic mechanics of writing vectors to (and checking
membership in) an ``embeddings``-shaped table:

    - plain-list → pgvector.Vector conversion (asyncpg codec requirement)
    - dimension validation against the configured table dimensions
    - row construction and commit
    - "already embedded" exclusion filters for dedup

The concrete SQLAlchemy model is **framework-owned** and lives in
``app/intelligence/models/embeddings.py`` (moved out of Stock in Gate 4.2);
``PgVectorStore`` resolves to it by default. ``PgVectorStore`` remains
parameterizable so a legitimate domain-owned model of the same shape could
also be injected (injection is an access pattern, not ownership — §11.3).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.core.database import commit_session
from app.core.logging import get_logger

logger = get_logger(__name__)


def to_pgvector(vector: list[float], expected_dimensions: int) -> Any:
    """
    Convert a plain list to a pgvector.Vector and validate its dimension.

    The conversion matters because asyncpg serializes a plain Python list
    as text, which fails on the PostgreSQL ``vector`` column; the codec
    registered in app/core/database.py expects pgvector instances.
    """
    from pgvector.utils import Vector as PgVector

    if not isinstance(vector, PgVector):
        vector = PgVector(vector)

    dims = vector.dimensions() if hasattr(vector, "dimensions") else len(vector)
    if dims != expected_dimensions:
        raise ValueError(
            f"Embedding has {dims} dimensions but the embeddings table "
            f"expects {expected_dimensions}. Check EMBEDDING_MODEL and "
            "EMBEDDING_DIMENSIONS consistency."
        )
    return vector


def unembedded_filter(
    embedding_model: type,
    target_model: type,
    entity_type: str,
    domain: str,
) -> ColumnElement[bool]:
    """
    Build a NOT EXISTS filter: rows of ``target_model`` that have no
    embedding row yet for the given generic identity
    ``(domain, entity_type, target row id)``. This is the dedup gate
    used by ingestion workers so already-indexed content is never
    re-embedded.

    Args:
        embedding_model: the framework's embedding ORM class (defaults to
            ``app.intelligence.models.Embedding``; must expose ``domain`` /
            ``entity_type`` / ``entity_id`` columns).
        target_model: the domain content model (must expose ``id``).
        entity_type: the entity_type value used when storing embeddings.
        domain: the domain value used when storing embeddings (e.g. "stock").
    """
    return ~exists(
        select(1).where(
            embedding_model.domain == domain,
            embedding_model.entity_type == entity_type,
            embedding_model.entity_id == target_model.id,
        )
    )


class PgVectorStore:
    """
    Persists ``VectorRecord`` objects into an embeddings-shaped table.

    The model defaults to the framework-owned ``Embedding`` ORM
    (``app.intelligence.models.embeddings.Embedding``) so domains share one
    canonical model/table; a caller may still inject a model, but ownership
    of the ``embeddings`` schema stays with the framework (architecture
    §11.3: injection is an access pattern, ownership is an architectural
    decision).
    """

    def __init__(
        self,
        model: type | None = None,
        dimensions: int | None = None,
        default_model_name: str | None = None,
    ):
        from app.intelligence.models.embeddings import Embedding

        settings = get_settings()
        self.model = model or Embedding
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self.default_model_name = (
            default_model_name or settings.EMBEDDING_MODEL
        )

    async def store(self, session: AsyncSession, record: Any) -> Any:
        """
        Persist one record. ``record`` needs domain/entity_type/entity_id/
        content/vector/model/metadata attributes. Commits via the caller's
        session convention and returns the fresh row.
        """
        if not record.content or not record.content.strip():
            raise ValueError("Cannot store an embedding for empty content.")
        if not record.vector:
            raise ValueError(
                f"Embedding generation returned an empty vector for "
                f"{record.domain}/{record.entity_type}/{record.entity_id}"
            )
        if not record.domain or not str(record.domain).strip():
            raise ValueError(
                "Cannot store an embedding without a domain: the embeddings "
                "identity is (domain, entity_type, entity_id)."
            )

        embedding = to_pgvector(record.vector, self.dimensions)
        row = self.model(
            domain=record.domain,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            content=record.content,
            embedding=embedding,
            embedding_model=record.model or self.default_model_name,
            metadata_=record.metadata,
        )
        session.add(row)
        await commit_session(session)
        await session.refresh(row)

        logger.info(
            "Stored embedding for %s/%s/%s (%d dims)",
            record.domain,
            record.entity_type,
            record.entity_id,
            len(record.vector),
        )
        return row