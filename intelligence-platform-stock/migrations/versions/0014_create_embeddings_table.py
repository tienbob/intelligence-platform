"""create embeddings table (pgvector)

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-14

The ``embeddings`` table was originally created in migration 0001, but the
Rails ``db:schema:load`` path could not dump it (pgvector ``vector(3072)``
type is unknown to Rails), so the table was silently skipped. This migration
recreates it with the final schema state (vector(3072) per migration 0009).

Idempotent: uses ``IF NOT EXISTS`` so it is safe on environments where the
table already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure the pgvector extension exists (no-op if already enabled).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create the embeddings table with the final vector(3072) column type.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            id BIGSERIAL PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity_id BIGINT NOT NULL,
            content TEXT NOT NULL,
            embedding vector(3072),
            embedding_model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_entity_type ON embeddings (entity_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_entity_id ON embeddings (entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embeddings")