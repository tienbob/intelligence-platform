"""
Framework-owned ``embeddings`` ORM — generic pgvector vector index.

The ``embeddings`` table is shared by all intelligence domains:

    Stock:
        news
        events
        analyses
        SEC filings

    Future domains:
        HR
        legal
        research
        etc.

The model therefore belongs to the framework rather than any domain.

Generic identity
----------------

Every embedding is identified by:

    domain
    entity_type
    entity_id
    embedding_model

For example:

    domain       = "stock"
    entity_type  = "news"
    entity_id    = 123
    embedding_model = "text-embedding-3-small"

Domain-specific identifiers such as:

    company_id
    ticker
    candidate_id

must NOT become columns on this table. They belong in ``metadata`` JSONB
when a domain requires them for retrieval filtering.

Architecture
------------

The framework owns:

    - Embedding ORM
    - pgvector column
    - generic identity
    - vector dimensions
    - embedding model
    - metadata storage
    - indexes / uniqueness constraints

Domains own:

    - what gets embedded
    - entity_type values
    - embedding content
    - domain metadata
    - ingestion scheduling

See:

    docs/TABLE_OWNERSHIP.md
    docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md §11.1
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from pgvector.utils import Vector as PgVector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.database import Base


settings = get_settings()


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

EMBEDDING_DIMENSIONS = int(settings.EMBEDDING_DIMENSIONS)
EMBEDDING_MODEL = str(settings.EMBEDDING_MODEL).strip()

if EMBEDDING_DIMENSIONS <= 0:
    raise ValueError(
        "EMBEDDING_DIMENSIONS must be greater than zero."
    )

if not EMBEDDING_MODEL:
    raise ValueError(
        "EMBEDDING_MODEL must not be empty."
    )


class AsyncVector(Vector):
    """
    pgvector Vector type compatible with the application's asyncpg codec.

    Why this exists
    ---------------

    ``pgvector.sqlalchemy.Vector`` normally serializes a vector through its
    bind processor.

    This application registers pgvector's asyncpg binary codec in
    ``app/core/database.py``.

    The codec expects a pgvector-compatible value rather than an already
    serialized text representation.

    This type therefore passes a ``pgvector.Vector`` object through to the
    driver unchanged.

    The conversion is deliberately kept here at the database type boundary
    rather than leaking pgvector-specific behavior into domain services.
    """

    cache_ok = True

    def bind_processor(self, dialect):
        """
        Return a bind processor compatible with asyncpg's pgvector codec.
        """

        def process(value):
            if value is None:
                return None

            if isinstance(value, PgVector):
                return value

            return PgVector(value)

        return process


class Embedding(Base):
    """
    Framework-owned generic pgvector embedding.

    Identity:

        (domain, entity_type, entity_id, embedding_model)

    The vector dimensions are fixed by ``EMBEDDING_DIMENSIONS`` and must match
    the PostgreSQL ``vector(N)`` column created by the migrations.

    Domain-specific filtering information belongs in ``metadata`` JSONB.
    """

    __tablename__ = "embeddings"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    # ------------------------------------------------------------------
    # Generic identity
    # ------------------------------------------------------------------

    domain: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    entity_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Embedded source content
    # ------------------------------------------------------------------

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Vector
    # ------------------------------------------------------------------

    embedding: Mapped[list[float] | None] = mapped_column(
        AsyncVector(EMBEDDING_DIMENSIONS),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Embedding model
    # ------------------------------------------------------------------

    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=EMBEDDING_MODEL,
    )

    # ------------------------------------------------------------------
    # Domain-specific metadata
    # ------------------------------------------------------------------

    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Database indexes / constraints
    # ------------------------------------------------------------------

    __table_args__ = (
        # Generic lookup:
        #
        #   WHERE domain = ?
        #     AND entity_type = ?
        #     AND entity_id = ?
        #
        Index(
            "ix_embeddings_domain_entity",
            "domain",
            "entity_type",
            "entity_id",
        ),

        # Model-aware lookup:
        #
        #   WHERE domain = ?
        #     AND entity_type = ?
        #     AND entity_id = ?
        #     AND embedding_model = ?
        #
        Index(
            "ix_embeddings_domain_entity_model",
            "domain",
            "entity_type",
            "entity_id",
            "embedding_model",
        ),

        # Prevent duplicate vectors for the same entity/model.
        #
        # This is especially important when multiple workers can ingest the
        # same records concurrently.
        UniqueConstraint(
            "domain",
            "entity_type",
            "entity_id",
            "embedding_model",
            name="uq_embeddings_entity_model",
        ),
    )

    def __repr__(self) -> str:
        return (
            "Embedding("
            f"domain={self.domain!r}, "
            f"entity_type={self.entity_type!r}, "
            f"entity_id={self.entity_id!r}, "
            f"embedding_model={self.embedding_model!r}"
            ")"
        )