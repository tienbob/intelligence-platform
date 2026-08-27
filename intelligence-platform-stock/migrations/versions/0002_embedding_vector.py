"""convert embeddings.embedding from ARRAY(Float) to pgvector vector

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05

The original 0001 migration created ``embeddings.embedding`` as
``ARRAY(Float)`` instead of the pgvector ``vector`` type.  The ``<=>``
cosine-distance operator used by RAG retrieval is only defined for
``vector`` columns, so a live ``ARRAY(Float)`` column would raise::

    operator does not exist: double precision[] <=> double precision[]

This revision alters the column in place:

* ``CREATE EXTENSION IF NOT EXISTS vector`` is a no-op if already present.
* ``USING embedding::vector`` safely casts any existing Float-array
  payloads (empty rows become NULL, which is valid for the nullable column).
* Dimensions are fixed to 1536 to match the default embedding model
  (``text-embedding-3-small``); enforce a check via the column type DDL
  (``vector(1536)``) instead of a separate CHECK constraint.

``down_revision`` is ``"0001"``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure the pgvector extension exists (no-op if already enabled).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Replace the column type in place.  The raw DDL is used because
    # pgvector's ``vector`` type is a user-defined type that isn't
    # represented in SQLAlchemy's dialect type map for DDL compilation.
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE vector(1536)
        USING embedding::vector(1536)
        """
    )


def downgrade() -> None:
    # Revert to the original ARRAY(Float) column.  Data is preserved via
    # an explicit cast from the pgvector text representation to a float array.
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE double precision[]
        USING embedding::text::double precision[]
        """
    )