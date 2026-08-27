"""add unique index on stock_prices (company_id, interval, timestamp) and set default interval

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add a server default for interval and create a unique index to prevent duplicates
    op.alter_column(
        "stock_prices",
        "interval",
        existing_type=sa.String(length=10),
        server_default=sa.text("'1d'"),
        existing_nullable=False,
    )

    # Create unique index to enforce uniqueness at DB level
    op.create_unique_constraint(
        "uq_stock_prices_company_interval_timestamp",
        "stock_prices",
        ["company_id", "interval", "timestamp"],
    )


def downgrade() -> None:
    # Remove unique constraint and server default
    op.drop_constraint(
        "uq_stock_prices_company_interval_timestamp", "stock_prices", type_="unique"
    )
    op.alter_column(
        "stock_prices",
        "interval",
        existing_type=sa.String(length=10),
        server_default=None,
        existing_nullable=False,
    )
