"""add unique constraint to company_news join table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_company_news_company_news",
        "company_news",
        ["company_id", "news_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_company_news_company_news",
        "company_news",
        type_="unique",
    )
