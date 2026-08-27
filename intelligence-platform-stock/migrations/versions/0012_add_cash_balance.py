"""Add cash_balance column to portfolios table.

Revision ID: 0012
Revises: 0011_add_provider_record_id
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolios",
        sa.Column("cash_balance", sa.Float(), nullable=False, server_default="0"),
    )
    # Set existing portfolios' cash_balance to their capital value
    op.execute("UPDATE portfolios SET cash_balance = capital")


def downgrade() -> None:
    op.drop_column("portfolios", "cash_balance")