"""add unique constraints for financial statements and macro indicators

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_financial_statements_company_period",
        "financial_statements",
        ["company_id", "period"],
    )

    op.create_unique_constraint(
        "uq_economic_indicators_indicator_timestamp",
        "economic_indicators",
        ["indicator", "timestamp"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_financial_statements_company_period",
        "financial_statements",
        type_="unique",
    )
    op.drop_constraint(
        "uq_economic_indicators_indicator_timestamp",
        "economic_indicators",
        type_="unique",
    )
