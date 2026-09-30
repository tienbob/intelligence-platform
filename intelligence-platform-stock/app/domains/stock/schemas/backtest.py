"""
Pydantic schemas for backtesting API (Section 162, Phase 9).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


# ── Request schemas ──────────────────────────────────────────────

# Must stay in sync with SUPPORTED_STRATEGIES in scoring/backtest.py.
BacktestStrategy = Literal[
    "score_threshold",
    "momentum",
    "equal_weight",
    "portfolio_optimizer",
]


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Ticker = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.^-]+$")]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]


class StrategyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoreParameters(StrategyParameters):
    threshold: float = Field(default=70, ge=0, le=100, allow_inf_nan=False)
    rebalance_days: PositiveInteger = 21


class MomentumParameters(StrategyParameters):
    top_n: PositiveInteger = 5
    lookback_trading_days: PositiveInteger = 60
    rebalance_days: PositiveInteger = 21


class OptimizerParameters(StrategyParameters):
    rebalance_days: PositiveInteger = 21
    risk_profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    max_position_weight: float = Field(default=0.15, gt=0, le=1, allow_inf_nan=False)
    max_sector_weight: float = Field(default=0.30, gt=0, le=1, allow_inf_nan=False)
    volatility_lookback: PositiveInteger = 60


_PARAMETER_MODELS = {
    "score_threshold": ScoreParameters,
    "momentum": MomentumParameters,
    "equal_weight": StrategyParameters,
    "portfolio_optimizer": OptimizerParameters,
}


class BacktestRunRequest(BaseModel):
    """POST /api/v1/backtest/runs request (Section 162)."""

    name: Name
    strategy: BacktestStrategy = "score_threshold"
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(default=100000.0, gt=0, allow_inf_nan=False)
    benchmark_ticker: Ticker = "SPY"
    parameters: dict[str, Any] = Field(default_factory=dict)
    tickers: Optional[list[Ticker]] = Field(default=None, min_length=1)  # if None, use all tracked companies
    snapshot_id: Optional[int] = Field(default=None, gt=0)  # if set, run against a point-in-time snapshot

    @model_validator(mode="after")
    def _validate_period(self) -> "BacktestRunRequest":
        if (self.start_date.tzinfo is None) != (self.end_date.tzinfo is None):
            raise ValueError("start_date and end_date must use consistent time zones")
        self.parameters = _PARAMETER_MODELS[self.strategy].model_validate(self.parameters).model_dump(exclude_unset=True)
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class BacktestSnapshotRequest(BaseModel):
    """POST /api/v1/backtest/snapshots request (Section 162)."""

    name: Name
    as_of: datetime
    description: Optional[str] = None
    tickers: Optional[list[Ticker]] = Field(default=None, min_length=1)  # if None, use all tracked companies


# ── Response schemas ─────────────────────────────────────────────


class BacktestRunResponse(BaseModel):
    """Lean run summary — only fields rendered by the FE runs table."""

    id: int
    name: str
    strategy: str
    status: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    error_message: Optional[str] = None
    # Snapshot pinning disclosure (audit F12): which decision inputs were
    # pinned vs read live. Null for runs from before this field existed.
    snapshot_coverage: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class BacktestRunListResponse(BaseModel):
    """List of backtest runs."""

    runs: list[BacktestRunResponse]


class BacktestSnapshotResponse(BaseModel):
    """Lean snapshot row — only fields rendered by the FE table."""

    id: int
    name: str
    as_of: datetime
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class BacktestSnapshotListResponse(BaseModel):
    """List of backtest snapshots."""

    snapshots: list[BacktestSnapshotResponse]


class BacktestResultResponse(BaseModel):
    """Lean result — only metrics rendered by the Backtest detail view."""

    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    final_capital: Optional[float] = None
    equity_curve: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class BacktestTradeResponse(BaseModel):
    """Lean trade row — only fields rendered by the FE trades table."""

    id: int
    ticker: str
    action: str
    trade_date: datetime
    price: float
    shares: float
    amount: float

    model_config = {"from_attributes": True}


class BacktestTradeListResponse(BaseModel):
    """List of backtest trades."""

    trades: list[BacktestTradeResponse]


class BacktestBenchmarkResponse(BaseModel):
    """Lean benchmark — only comparison rendered by the FE detail view."""

    benchmark_ticker: str
    benchmark_return: Optional[float] = None
    strategy_return: Optional[float] = None
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
    """Lean run detail — drops score/AI evaluations the FE never renders."""

    run: BacktestRunResponse
    result: Optional[BacktestResultResponse] = None
    benchmark: Optional[BacktestBenchmarkResponse] = None
    trades: list[BacktestTradeResponse] = Field(default_factory=list)