"""resize embeddings.embedding to 3072 dimensions

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-06

The configured embedding model (gemini-embedding-001) produces 3072
dimensions, but migration 0002 hardcoded the column to vector(1536).
This revision alters the column to vector(3072) to match the model.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE vector(3072)
        USING embedding::vector(3072)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE vector(1536)
        USING embedding::vector(1536)
        """
    )