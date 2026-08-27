"""
Pydantic schemas for the portfolio optimizer (Section 49).

Only the stateless optimizer is kept; the portfolio-management CRUD and
operations schemas have been removed along with the portfolio-management
backend.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PortfolioOptimizeRequest(BaseModel):
    """POST /api/v1/portfolio/optimize request (Section 49)."""

    capital: float
    cash_reserve: float = 0
    risk_profile: str = "moderate"  # conservative | moderate | aggressive
    investment_horizon: str = "long_term"
    max_position_weight: float = 0.15
    max_sector_weight: float = 0.30
    max_portfolio_volatility: Optional[float] = None
    tickers: Optional[list[str]] = None  # if None, use top opportunities


class PortfolioAllocation(BaseModel):
    """A single allocation."""

    ticker: str
    amount: float
    investable_weight: float
    portfolio_weight: float


class PortfolioRiskMetrics(BaseModel):
    """Expanded portfolio risk metrics."""

    expected_risk: Optional[float] = None
    volatility: Optional[float] = None
    max_drawdown: Optional[float] = None
    beta: Optional[float] = None
    sharpe_ratio: Optional[float] = None


class PortfolioDataQuality(BaseModel):
    """Data quality for portfolio-level calculations."""

    risk_metrics_available: bool = False
    reason: str = "insufficient historical data for risk calculations"


class PortfolioMetrics(BaseModel):
    """Portfolio-level metrics."""

    weighted_investment_score: float
    diversification_score: float
    risk: PortfolioRiskMetrics
    data_quality: PortfolioDataQuality


class PortfolioOptimizeResponse(BaseModel):
    """POST /api/v1/portfolio/optimize response (Section 49)."""

    capital: float
    cash_reserve: float
    investable_capital: float
    allocated_capital: float
    unallocated_capital: float
    unallocated_reason: str = "unknown"
    allocation: list[PortfolioAllocation] = Field(default_factory=list)
    portfolio: PortfolioMetrics
    explanation: Optional[str] = None