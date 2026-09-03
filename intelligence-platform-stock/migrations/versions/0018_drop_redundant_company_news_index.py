"""drop redundant company_news index (P2 fix)

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-27

Follows MIGRATION_FIX_PLAN.md §P2: the plain index ``ix_company_news_company_news``
created back in 0001 (P1) is fully redundant with the unique constraint
``uq_company_news_company_news`` added by 0005, because both cover
``(company_id, news_id)``. The unique constraint already backs an
implicit index, so the standalone one is dead weight.

Only the redundant B-tree index is dropped — the underlying ``company_news``
table and its unique constraint are untouched.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_company_news_company_news", table_name="company_news")


def downgrade() -> None:
    op.create_index(
        "ix_company_news_company_news",
        "company_news",
        ["company_id", "news_id"],
    )
