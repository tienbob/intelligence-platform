"""
Company model — canonical entity for all tracked public companies.

Implements entity resolution (Section 14): different providers may represent
the same company differently (Apple Inc., Apple, AAPL, NASDAQ:AAPL, …).
All should resolve to a single ``companies`` row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50))
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    cusip: Mapped[str | None] = mapped_column(String(9))
    country: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(100), index=True)
    industry: Mapped[str | None] = mapped_column(String(255))
    market_cap: Mapped[float | None] = mapped_column()
    description: Mapped[str | None] = mapped_column()
    website: Mapped[str | None] = mapped_column(String(500))
    # Instrument discriminator (see docs/PLAN_INSTRUMENT_TYPE.md).
    # Values: common_stock | etf | mutual_fund | unknown.
    # The ORM default is "unknown" so a newly-created row is never silently
    # treated as a stock before classification runs.
    instrument_type: Mapped[str] = mapped_column(
        String(20), default="unknown", index=True
    )

    __table_args__ = (
        Index("ix_companies_ticker_exchange", "ticker", "exchange", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Company(id={self.id}, ticker={self.ticker!r})>"