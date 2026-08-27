"""
Market event and event-price-correlation models (Sections 15, 23, 26).

* ``MarketEvent`` — classified events (earnings beat, regulatory, etc.).
* ``EventPriceCorrelation`` — market response to important events.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class MarketEvent(Base, TimestampMixin):
    __tablename__ = "market_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    impact: Mapped[str | None] = mapped_column(String(20))  # positive | negative | neutral
    impact_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    confidence: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    materiality_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1 (Section 45)
    effective_weight: Mapped[float | None] = mapped_column(Float)  # 0 .. 1 (Section 46)
    description: Mapped[str | None] = mapped_column(Text)
    source_news_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news.id")
    )

    __table_args__ = (
        Index("ix_market_events_company_date", "company_id", "event_date"),
        # Phase 4: prevent duplicate events from same news for same company.
        # One news article produces one canonical event per company; the
        # classification can subsequently be updated in place.
        Index(
            "uq_market_events_company_news",
            "company_id",
            "source_news_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<MarketEvent(type={self.event_type!r}, date={self.event_date})>"


class EventPriceCorrelation(Base, TimestampMixin):
    """Records the market response to important events (Section 26)."""

    __tablename__ = "event_price_correlations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market_events.id"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    price_before: Mapped[float | None] = mapped_column(Float)
    price_after: Mapped[float | None] = mapped_column(Float)
    price_change: Mapped[float | None] = mapped_column(Float)
    volume_change: Mapped[float | None] = mapped_column(Float)
    volatility_change: Mapped[float | None] = mapped_column(Float)
    time_to_reaction_min: Mapped[int | None] = mapped_column(BigInteger)

    def __repr__(self) -> str:
        return f"<EventPriceCorrelation(event_id={self.event_id}, change={self.price_change})>"