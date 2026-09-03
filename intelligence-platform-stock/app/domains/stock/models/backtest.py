"""
Backtesting models (Section 162, Phase 9).

* ``BacktestRun`` — a single backtest execution with strategy and parameters.
* ``BacktestSnapshot`` — point-in-time data snapshot used for a backtest.
* ``BacktestResult`` — performance metrics from a backtest run.
* ``BacktestTrade`` — simulated trade executed during a backtest.
* ``BacktestBenchmark`` — benchmark comparison results.
* ``BacktestScoreEvaluation`` — evaluation of investment scores vs actual outcomes.
* ``BacktestAIEvaluation`` — evaluation of AI analysis quality.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class BacktestRun(Base, TimestampMixin):
    """A single backtest execution (Section 162)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # strategy: score_threshold | momentum | equal_weight | portfolio_optimizer
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # queued | running | completed | failed

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=100000.0)
    benchmark_ticker: Mapped[str | None] = mapped_column(String(20), default="SPY")

    # Strategy parameters (JSONB)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Point-in-time dataset reference
    snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("backtest_snapshots.id"), nullable=True
    )

    # Versioning (Section 162: reproducibility)
    scoring_model: Mapped[str | None] = mapped_column(String(50))
    scoring_version: Mapped[str | None] = mapped_column(String(20))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    data_version: Mapped[str | None] = mapped_column(String(50))

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<BacktestRun(id={self.id}, strategy={self.strategy!r}, status={self.status!r})>"


class BacktestSnapshot(Base, TimestampMixin):
    """Point-in-time data snapshot for backtesting (Section 162)."""

    __tablename__ = "backtest_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Snapshot contents (JSONB): prices, scores, fundamentals, events, news
    prices: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fundamentals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    events: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    news: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Provenance
    source_data_version: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<BacktestSnapshot(id={self.id}, as_of={self.as_of})>"


class BacktestResult(Base, TimestampMixin):
    """Performance metrics from a backtest run (Section 162)."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )

    # Performance metrics
    total_return: Mapped[float | None] = mapped_column(Float)
    annualized_return: Mapped[float | None] = mapped_column(Float)
    volatility: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    total_trades: Mapped[int | None] = mapped_column(BigInteger)
    final_capital: Mapped[float | None] = mapped_column(Float)

    # Equity curve (JSONB: list of {date, value})
    equity_curve: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Trade list reference
    trade_count: Mapped[int | None] = mapped_column(BigInteger)

    def __repr__(self) -> str:
        return f"<BacktestResult(run_id={self.run_id}, total_return={self.total_return})>"


class BacktestTrade(Base, TimestampMixin):
    """Simulated trade executed during a backtest (Section 162)."""

    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY | SELL
    trade_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("ix_backtest_trades_run_date", "run_id", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<BacktestTrade(run_id={self.run_id}, ticker={self.ticker!r}, action={self.action!r})>"


class BacktestBenchmark(Base, TimestampMixin):
    """Benchmark comparison results (Section 162)."""

    __tablename__ = "backtest_benchmarks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    benchmark_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    strategy_return: Mapped[float | None] = mapped_column(Float)
    alpha: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    tracking_error: Mapped[float | None] = mapped_column(Float)
    information_ratio: Mapped[float | None] = mapped_column(Float)
    outperformed: Mapped[bool | None] = mapped_column(Boolean)

    def __repr__(self) -> str:
        return f"<BacktestBenchmark(run_id={self.run_id}, ticker={self.benchmark_ticker!r})>"


class BacktestScoreEvaluation(Base, TimestampMixin):
    """Evaluation of investment scores vs actual outcomes (Section 162)."""

    __tablename__ = "backtest_score_evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    score_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(String(20))
    forward_return_1m: Mapped[float | None] = mapped_column(Float)
    forward_return_3m: Mapped[float | None] = mapped_column(Float)
    forward_return_6m: Mapped[float | None] = mapped_column(Float)
    actual_outcome: Mapped[str | None] = mapped_column(String(20))
    # actual_outcome: POSITIVE | NEGATIVE | NEUTRAL

    __table_args__ = (
        Index("ix_backtest_score_eval_run_ticker", "run_id", "ticker"),
    )

    def __repr__(self) -> str:
        return f"<BacktestScoreEvaluation(run_id={self.run_id}, ticker={self.ticker!r})>"


class BacktestAIEvaluation(Base, TimestampMixin):
    """Evaluation of AI analysis quality (Section 162)."""

    __tablename__ = "backtest_ai_evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    analysis_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analyses.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    analysis_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    llm_confidence: Mapped[float | None] = mapped_column(Float)
    llm_direction: Mapped[str | None] = mapped_column(String(20))
    # llm_direction: bullish | bearish | neutral
    actual_direction: Mapped[str | None] = mapped_column(String(20))
    # actual_direction: up | down | flat
    direction_accuracy: Mapped[bool | None] = mapped_column(Boolean)
    forward_return: Mapped[float | None] = mapped_column(Float)
    evidence_count: Mapped[int | None] = mapped_column(BigInteger)
    source_backed: Mapped[bool | None] = mapped_column(Boolean)

    def __repr__(self) -> str:
        return f"<BacktestAIEvaluation(run_id={self.run_id}, ticker={self.ticker!r})>"