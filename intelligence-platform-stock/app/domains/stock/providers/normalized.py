"""
Normalized provider models (Section 6).

All providers return data in these normalized formats, regardless of the
underlying provider's API shape. This ensures the application never depends
on provider-specific response structures.

Flow:
    Provider Interface → Provider Adapter → Normalized Model
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class NormalizedQuote(BaseModel):
    """Normalized stock quote from any market-data provider."""

    ticker: str
    price: float
    change: float = 0
    change_percent: float = 0
    volume: int = 0
    timestamp: Optional[datetime] = None
    provider: str = "unknown"


class NormalizedPricePoint(BaseModel):
    """Normalized OHLCV price point from any provider."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: Optional[float] = None
    volume: int = 0


class NormalizedPriceHistory(BaseModel):
    """Normalized historical price series."""

    ticker: str
    interval: str = "1d"
    prices: list[NormalizedPricePoint] = Field(default_factory=list)


class NormalizedMarketMover(BaseModel):
    """Normalized market mover (gainer/loser)."""

    ticker: str
    name: Optional[str] = None
    price: float
    change_percent: float
    volume: int = 0


class NormalizedMarketMovers(BaseModel):
    gainers: list[NormalizedMarketMover] = Field(default_factory=list)
    losers: list[NormalizedMarketMover] = Field(default_factory=list)


class NormalizedNews(BaseModel):
    """Normalized news article from any news provider."""

    external_id: Optional[str] = None
    source: str
    title: str
    url: Optional[str] = None
    published_at: datetime
    summary: Optional[str] = None
    content: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    sentiment: Optional[float] = Field(default=None, ge=-1, le=1)


class NormalizedFinancialStatement(BaseModel):
    """Normalized financial statement (income / balance / cash-flow merged)."""

    period: str
    period_type: str = "quarterly"  # annual | quarterly
    currency: str = "USD"
    # Income
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    # Balance
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    shareholders_equity: Optional[float] = None
    # Cash flow
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    free_cash_flow: Optional[float] = None
    # Provenance
    source: str = "unknown"
    source_id: Optional[str] = None
    filed_date: Optional[datetime] = None


class NormalizedEconomicIndicator(BaseModel):
    """Normalized macro economic indicator data point."""

    indicator: str
    timestamp: datetime
    value: float
    unit: Optional[str] = None
    source: str = "FRED"
    frequency: Optional[str] = None


class NormalizedInsiderTransaction(BaseModel):
    """Normalized insider transaction."""

    ticker: str
    transaction_date: Optional[datetime] = None
    insider_name: Optional[str] = None
    transaction_type: Optional[str] = None
    shares: Optional[float] = None
    price: Optional[float] = None
    value: Optional[float] = None
    ownership_change: Optional[float] = None
    source: str = "unknown"


class NormalizedInstitutionalOwnership(BaseModel):
    """Normalized institutional / fund ownership data."""

    ticker: str
    filing_date: Optional[datetime] = None
    institution: Optional[str] = None
    shares: Optional[float] = None
    value: Optional[float] = None
    percent_change: Optional[float] = None
    source: str = "unknown"