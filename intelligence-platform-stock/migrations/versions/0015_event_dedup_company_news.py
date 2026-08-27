"""event dedup: one canonical event per news article per company

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-19

Changes the market_events uniqueness from
    (company_id, source_news_id, event_type)
to
    (company_id, source_news_id)

One news article now produces one canonical event per company; the
classification can subsequently be updated in place. Existing duplicate
rows (same company+news with different event types) are collapsed to a
single row before applying the new constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # De-duplicate existing rows: keep the highest-id row per
    # (company_id, source_news_id), dropping older duplicates so the
    # new unique constraint can be applied cleanly.
    op.execute(
        """
        DELETE FROM market_events a
        USING market_events b
        WHERE a.company_id IS NOT DISTINCT FROM b.company_id
          AND a.source_news_id IS NOT DISTINCT FROM b.source_news_id
          AND a.id < b.id
        """
    )

    # Replace the old (company_id, source_news_id, event_type) constraint
    # with the new (company_id, source_news_id) constraint.
    op.drop_constraint(
        "uq_market_events_company_news_type",
        "market_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_market_events_company_news",
        "market_events",
        ["company_id", "source_news_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_market_events_company_news",
        "market_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_market_events_company_news_type",
        "market_events",
        ["company_id", "source_news_id", "event_type"],
    )