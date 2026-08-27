"""add materiality and effective_weight columns to events and news

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-05

Phase 4 (#157): News-event correlation scoring and materiality ranking.
- market_events: materiality_score, effective_weight, uniqueness constraint on (company_id, source_news_id, event_type)
- news: materiality_score, effective_weight
- company_news: extraction_method, confidence columns (Section 24)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── market_events: materiality & effective weight ───────────
    op.add_column("market_events", sa.Column("materiality_score", sa.Float(), nullable=True))
    op.add_column("market_events", sa.Column("effective_weight", sa.Float(), nullable=True))

    # Prevent duplicate events from the same news article for the same company+type
    op.create_unique_constraint(
        "uq_market_events_company_news_type",
        "market_events",
        ["company_id", "source_news_id", "event_type"],
    )

    # ── news: materiality & effective weight (Section 45-46) ────
    op.add_column("news", sa.Column("materiality_score", sa.Float(), nullable=True))
    op.add_column("news", sa.Column("effective_weight", sa.Float(), nullable=True))

    # ── company_news: extraction metadata (Section 24) ──────────
    op.add_column("company_news", sa.Column("extraction_method", sa.String(length=50), nullable=True))
    op.add_column("company_news", sa.Column("confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_news", "confidence")
    op.drop_column("company_news", "extraction_method")
    op.drop_column("news", "effective_weight")
    op.drop_column("news", "materiality_score")

    op.drop_constraint("uq_market_events_company_news_type", "market_events", type_="unique")

    op.drop_column("market_events", "effective_weight")
    op.drop_column("market_events", "materiality_score")