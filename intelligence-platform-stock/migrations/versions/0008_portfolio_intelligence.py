"""Phase 7: Portfolio intelligence — allocation history, rebalance trades, drift alerts.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### Portfolio allocation history (Section 39) ###
    op.create_table(
        "portfolio_allocation_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.BigInteger(), sa.ForeignKey("portfolios.id"), nullable=False, index=True),
        sa.Column("recommendation_id", sa.BigInteger(), sa.ForeignKey("portfolio_recommendations.id"), nullable=True),
        sa.Column("allocation", postgresql.JSONB(), nullable=True),
        sa.Column("portfolio_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("cash_reserve", sa.Float(), nullable=True),
        sa.Column("investable_capital", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Portfolio rebalance trades (Section 39) ###
    op.create_table(
        "portfolio_rebalance_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.BigInteger(), sa.ForeignKey("portfolios.id"), nullable=False, index=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),  # BUY | SELL | HOLD
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("current_weight", sa.Float(), nullable=False),
        sa.Column("weight_delta", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),  # PENDING | EXECUTED | SKIPPED
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Portfolio drift alerts (Section 39) ###
    op.create_table(
        "portfolio_drift_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.BigInteger(), sa.ForeignKey("portfolios.id"), nullable=False, index=True),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("drift_type", sa.String(50), nullable=False),  # POSITION_DRIFT | SECTOR_DRIFT | CASH_DRIFT | RISK_DRIFT
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("portfolio_drift_alerts")
    op.drop_table("portfolio_rebalance_trades")
    op.drop_table("portfolio_allocation_history")