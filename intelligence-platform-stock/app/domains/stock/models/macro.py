"""
Macroeconomic indicator model (Section 15).

Stores time-series data from FRED: interest rates, inflation, GDP, etc.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class EconomicIndicator(Base, TimestampMixin):
    __tablename__ = "economic_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="FRED")
    frequency: Mapped[str | None] = mapped_column(String(20))  # daily, monthly, quarterly…

    __table_args__ = (
        Index(
            "ix_economic_indicators_indicator_ts",
            "indicator",
            "timestamp",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<EconomicIndicator({self.indicator!r}, value={self.value})>"