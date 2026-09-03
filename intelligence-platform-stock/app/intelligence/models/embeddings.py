"""
Framework-owned ``embeddings`` ORM — generic pgvector vector index (Gate 4.2).

The ``embeddings`` table serves **any** domain (Stock news/events/analyses,
a future HR candidate/review, a legal case, …), so the model belongs to the
framework, not to a domain layer. Identity is fully generic — the persistence
equivalent of ``EntityRef``:

    domain       which domain owns the entity                  (e.g. "stock")
    entity_type  what kind of entity it is                     (e.g. "news")
    entity_id    primary key of the entity in its domain table (e.g. news.id)

Domain-specific identifiers (``company_id``, ``ticker``, ``candidate_id``)
are forbidden as columns; they belong in the JSONB ``metadata`` if a domain
needs them for filtering. See ``docs/TABLE_OWNERSHIP.md`` (framework-owned) and
``docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md`` §11.1.

Lives at ``app/intelligence/models/embeddings.py`` and is re-exported through
``app.intelligence.embeddings`` so domains consume it via the framework
contract surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector
from pgvector.utils import Vector as PgVector

from app.core.config import get_settings
from app.core.database import Base

settings = get_settings()


class AsyncVector(Vector):
    """
    pgvector Vector type that passes values through to asyncpg's binary codec.

    The stock ``Vector.bind_processor`` serializes the value to a text string
    (``"[0.1, 0.2, ...]"``) before asyncpg sees it.  asyncpg's registered
    binary codec (``register_vector``) then fails to encode that string as a
    vector ("could not convert string to float").  This subclass overrides the
    bind processor to return a ``pgvector.Vector`` object unchanged, so the
    asyncpg binary codec receives the correct type.
    """

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if not isinstance(value, PgVector):
                value = PgVector(value)
            return value

        return process


class Embedding(Base):
    """pgvector embedding for generic RAG retrieval (Section 28)."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Generic identity (architecture §11.1) ────────────────────
    domain: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    entity_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # pgvector column — width must match migrations 0002/0009 (vector(3072));
    # the startup check in app/core/database.py verifies the live column.
    embedding: Mapped[list[float] | None] = mapped_column(
        AsyncVector(settings.EMBEDDING_DIMENSIONS), nullable=True
    )
    embedding_model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="text-embedding-3-small"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_embeddings_domain_entity", "domain", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Embedding(domain={self.domain!r}, entity_type={self.entity_type!r}, "
            f"entity_id={self.entity_id})>"
        )