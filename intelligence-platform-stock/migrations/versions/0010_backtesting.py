"""Phase 9: Backtesting — point-in-time datasets, strategy evaluation, benchmark comparison.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### Backtest snapshots (Section 162: point-in-time datasets) ###
    op.create_table(
        "backtest_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prices", postgresql.JSONB(), nullable=True),
        sa.Column("scores", postgresql.JSONB(), nullable=True),
        sa.Column("fundamentals", postgresql.JSONB(), nullable=True),
        sa.Column("events", postgresql.JSONB(), nullable=True),
        sa.Column("news", postgresql.JSONB(), nullable=True),
        sa.Column("source_data_version", sa.String(50), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Backtest runs ###
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Float(), nullable=False, server_default="100000"),
        sa.Column("benchmark_ticker", sa.String(20), nullable=True, server_default="SPY"),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("backtest_snapshots.id"), nullable=True),
        sa.Column("scoring_model", sa.String(50), nullable=True),
        sa.Column("scoring_version", sa.String(20), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("data_version", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Backtest results ###
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("total_return", sa.Float(), nullable=True),
        sa.Column("annualized_return", sa.Float(), nullable=True),
        sa.Column("volatility", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("total_trades", sa.BigInteger(), nullable=True),
        sa.Column("final_capital", sa.Float(), nullable=True),
        sa.Column("equity_curve", postgresql.JSONB(), nullable=True),
        sa.Column("trade_count", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Backtest trades ###
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),  # BUY | SELL
        sa.Column("trade_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_backtest_trades_run_date", "backtest_trades", ["run_id", "trade_date"])

    # ### Backtest benchmarks ###
    op.create_table(
        "backtest_benchmarks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("benchmark_ticker", sa.String(20), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("strategy_return", sa.Float(), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("tracking_error", sa.Float(), nullable=True),
        sa.Column("information_ratio", sa.Float(), nullable=True),
        sa.Column("outperformed", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ### Backtest score evaluations ###
    op.create_table(
        "backtest_score_evaluations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("score_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=True),
        sa.Column("forward_return_1m", sa.Float(), nullable=True),
        sa.Column("forward_return_3m", sa.Float(), nullable=True),
        sa.Column("forward_return_6m", sa.Float(), nullable=True),
        sa.Column("actual_outcome", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_backtest_score_eval_run_ticker", "backtest_score_evaluations", ["run_id", "ticker"])

    # ### Backtest AI evaluations ###
    op.create_table(
        "backtest_ai_evaluations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("analysis_id", sa.BigInteger(), sa.ForeignKey("analyses.id"), nullable=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("analysis_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("llm_direction", sa.String(20), nullable=True),
        sa.Column("actual_direction", sa.String(20), nullable=True),
        sa.Column("direction_accuracy", sa.Boolean(), nullable=True),
        sa.Column("forward_return", sa.Float(), nullable=True),
        sa.Column("evidence_count", sa.BigInteger(), nullable=True),
        sa.Column("source_backed", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_ai_evaluations")
    op.drop_table("backtest_score_evaluations")
    op.drop_table("backtest_benchmarks")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_results")
    op.drop_table("backtest_runs")
    op.drop_table("backtest_snapshots")