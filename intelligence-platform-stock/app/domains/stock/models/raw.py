"""
Raw data layer models (Section 8).

Raw data represents the original provider response, preserved for
reprocessing, auditing, debugging, provider migration, and data lineage.
Raw data should not be used directly by the LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class RawMarketData(Base, TimestampMixin):
    __tablename__ = "raw_market_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_raw_market_data_provider_ticker", "provider", "ticker"),
    )


class RawSecFiling(Base, TimestampMixin):
    __tablename__ = "raw_sec_filings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="SEC")
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True)
    filing_type: Mapped[str | None] = mapped_column(String(20), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RawNews(Base, TimestampMixin):
    __tablename__ = "raw_news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RawMacroData(Base, TimestampMixin):
    __tablename__ = "raw_macro_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="FRED")
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    indicator: Mapped[str | None] = mapped_column(String(100), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)