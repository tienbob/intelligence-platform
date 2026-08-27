"""Add provider_record_id column to stock_prices.

Fixes schema drift: the StockPrice ORM model declares `provider_record_id`
but no migration ever created the column, causing UndefinedColumnError on
queries that select all StockPrice columns (e.g. market movers / top-movers).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the missing nullable provider_record_id column (matches the ORM model).
    op.add_column(
        "stock_prices",
        sa.Column("provider_record_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_prices", "provider_record_id")