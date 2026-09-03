"""add generic ``domain`` identity to embeddings (Gate 4.2)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-03

The ``embeddings`` table is framework-owned (docs/TABLE_OWNERSHIP.md) and is
meant to serve ANY domain (Stock news/events/analyses today, HR/legal later).
Its identity must be fully generic — the persistence equivalent of
``EntityRef`` (docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md §11.1):

    (domain, entity_type, entity_id)

Previously the table only had ``entity_type`` / ``entity_id``; there was no
``domain`` column, so cross-domain uniqueness was impossible and Stock's
identity leaked into the framework schema.

This migration:

* adds ``embeddings.domain VARCHAR(50) NOT NULL``;
* backfills every existing row with ``'stock'`` (all rows today are Stock's);
* drops the server default afterwards so the framework can NOT silently write
  a ``domain`` — every future write must provide the identity explicitly
  (``VectorRecord.domain`` / ``PgVectorStore`` enforce this at the app layer);
* adds the composite identity index ``ix_embeddings_domain_entity`` matching
  the ORM ``Index("ix_embeddings_domain_entity", ...)`` and the single-column
  ``index=True`` on ``domain``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add with a default so ADD COLUMN fills the existing (all-Stock) rows.
    op.add_column(
        "embeddings",
        sa.Column(
            "domain",
            sa.String(length=50),
            server_default=sa.text("'stock'"),
            nullable=False,
        ),
    )
    # Explicit backfill for clarity (above is authoritative; belt-and-braces).
    op.execute(
        "UPDATE embeddings SET domain = 'stock' WHERE domain IS NULL"
    )
    # Force explicit identity on future writes — no silent 'stock' default.
    op.alter_column(
        "embeddings", "domain",
        server_default=None,
        nullable=False,
    )

    op.create_index(
        "ix_embeddings_domain", "embeddings", ["domain"]
    )
    # Composite identity index (ORM: Index("ix_embeddings_domain_entity", ...)).
    op.create_index(
        "ix_embeddings_domain_entity",
        "embeddings",
        ["domain", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_embeddings_domain_entity", table_name="embeddings"
    )
    op.drop_index(
        "ix_embeddings_domain", table_name="embeddings"
    )
    op.drop_column("embeddings", "domain")