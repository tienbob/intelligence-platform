"""
Stock price model — canonical OHLCV data (Section 15).

Indexed on (company_id, timestamp) for fast time-series queries.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class StockPrice(Base, TimestampMixin):
    __tablename__ = "stock_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    interval: Mapped[str] = mapped_column(String(10), nullable=False, default="1d")
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="massive")
    provider_record_id: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index("ix_stock_prices_company_timestamp", "company_id", "timestamp"),
        Index("ix_stock_prices_company_interval_ts", "company_id", "interval", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<StockPrice(company_id={self.company_id}, ts={self.timestamp}, close={self.close})>"