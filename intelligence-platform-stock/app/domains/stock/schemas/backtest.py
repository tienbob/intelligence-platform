"""
Pydantic schemas for backtesting API (Section 162, Phase 9).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ── Request schemas ──────────────────────────────────────────────

# Must stay in sync with SUPPORTED_STRATEGIES in scoring/backtest.py.
BacktestStrategy = Literal[
    "score_threshold",
    "momentum",
    "equal_weight",
    "portfolio_optimizer",
]


class BacktestRunRequest(BaseModel):
    """POST /api/v1/backtest/runs request (Section 162)."""

    name: str
    strategy: BacktestStrategy = "score_threshold"
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(default=100000.0, gt=0)
    benchmark_ticker: str = "SPY"
    parameters: dict[str, Any] = Field(default_factory=dict)
    tickers: Optional[list[str]] = None  # if None, use all tracked companies
    snapshot_id: Optional[int] = None  # if set, run against a point-in-time snapshot

    @model_validator(mode="after")
    def _validate_period(self) -> "BacktestRunRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class BacktestSnapshotRequest(BaseModel):
    """POST /api/v1/backtest/snapshots request (Section 162)."""

    name: str
    as_of: datetime
    description: Optional[str] = None
    tickers: Optional[list[str]] = None  # if None, use all tracked companies


# ── Response schemas ─────────────────────────────────────────────


class BacktestRunResponse(BaseModel):
    """Backtest run summary."""

    id: int
    name: str
    strategy: str
    status: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    benchmark_ticker: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None
    snapshot_id: Optional[int] = None
    scoring_model: Optional[str] = None
    scoring_version: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BacktestRunListResponse(BaseModel):
    """List of backtest runs."""

    runs: list[BacktestRunResponse]
    total: int


class BacktestSnapshotResponse(BaseModel):
    """Backtest snapshot summary."""

    id: int
    name: str
    as_of: datetime
    description: Optional[str] = None
    source_data_version: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BacktestSnapshotListResponse(BaseModel):
    """List of backtest snapshots."""

    snapshots: list[BacktestSnapshotResponse]
    total: int


class BacktestResultResponse(BaseModel):
    """Backtest performance metrics."""

    id: int
    run_id: int
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    final_capital: Optional[float] = None
    equity_curve: Optional[dict[str, Any]] = None
    trade_count: Optional[int] = None

    model_config = {"from_attributes": True}


class BacktestTradeResponse(BaseModel):
    """Simulated trade."""

    id: int
    run_id: int
    ticker: str
    action: str
    trade_date: datetime
    price: float
    shares: float
    amount: float
    reason: Optional[str] = None

    model_config = {"from_attributes": True}


class BacktestTradeListResponse(BaseModel):
    """List of backtest trades."""

    trades: list[BacktestTradeResponse]
    total: int


class BacktestBenchmarkResponse(BaseModel):
    """Benchmark comparison."""

    id: int
    run_id: int
    benchmark_ticker: str
    benchmark_return: Optional[float] = None
    strategy_return: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None
    outperformed: Optional[bool] = None

    model_config = {"from_attributes": True}


class BacktestScoreEvaluationResponse(BaseModel):
    """Score evaluation result."""

    id: int
    run_id: int
    ticker: str
    score_date: datetime
    score: float
    recommendation: Optional[str] = None
    forward_return_1m: Optional[float] = None
    forward_return_3m: Optional[float] = None
    forward_return_6m: Optional[float] = None
    actual_outcome: Optional[str] = None

    model_config = {"from_attributes": True}


class BacktestAIEvaluationResponse(BaseModel):
    """AI evaluation result."""

    id: int
    run_id: int
    analysis_id: Optional[int] = None
    ticker: str
    analysis_date: datetime
    llm_confidence: Optional[float] = None
    llm_direction: Optional[str] = None
    actual_direction: Optional[str] = None
    direction_accuracy: Optional[bool] = None
    forward_return: Optional[float] = None
    evidence_count: Optional[int] = None
    source_backed: Optional[bool] = None

    model_config = {"from_attributes": True}


class BacktestRunDetailResponse(BaseModel):
    """Full backtest run detail with results."""

    run: BacktestRunResponse
    result: Optional[BacktestResultResponse] = None
    benchmark: Optional[BacktestBenchmarkResponse] = None
    trades: list[BacktestTradeResponse] = Field(default_factory=list)
    score_evaluations: list[BacktestScoreEvaluationResponse] = Field(default_factory=list)
    ai_evaluations: list[BacktestAIEvaluationResponse] = Field(default_factory=list)