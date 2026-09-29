"""Analysis source claim values: Float -> String.

LLM claim values are not always numeric (e.g. ``ceo_transition`` values
like "John Ternus"), so the column stores values verbatim. Mirrors Rails
migration 20260929000000 (shared DB, dual migration history).

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "analysis_sources",
        "value",
        existing_type=sa.Float(),
        type_=sa.String(length=100),
        postgresql_using="value::varchar",
    )


def downgrade() -> None:
    op.alter_column(
        "analysis_sources",
        "value",
        existing_type=sa.String(length=100),
        type_=sa.Float(),
        postgresql_using="value::float",
    )