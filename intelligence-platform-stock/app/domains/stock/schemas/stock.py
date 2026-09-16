"""
Pydantic schemas for stock / price API responses (Sections 44–45).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """Real-time or latest stock quote (Section 44)."""

    ticker: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: int
    timestamp: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StockPricePoint(BaseModel):
    """Single OHLCV data point — only fields rendered by the FE price table."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    model_config = {"from_attributes": True}


class StockPriceHistory(BaseModel):
    """Historical price response (Section 45)."""

    ticker: str
    interval: str = "1d"
    prices: list[StockPricePoint]


class MarketMover(BaseModel):
    ticker: str
    name: Optional[str] = None
    price: float
    change_percent: float
    volume: int


class MarketMoversResponse(BaseModel):
    gainers: list[MarketMover] = Field(default_factory=list)
    losers: list[MarketMover] = Field(default_factory=list)