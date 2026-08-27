"""
Financial statement and metrics models (Sections 15).

* ``FinancialStatement`` — canonical normalised income / balance / cash-flow data.
* ``FinancialMetric`` — derived ratios calculated by the fundamental engine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import ProvenanceMixin, TimestampMixin


class FinancialStatement(Base, TimestampMixin, ProvenanceMixin):
    """Normalised financial statement combining income, balance-sheet, and cash-flow."""

    __tablename__ = "financial_statements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. 2026-Q2
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # annual | quarterly
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    filing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Income statement
    revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)

    # Balance sheet
    total_assets: Mapped[float | None] = mapped_column(Float)
    total_liabilities: Mapped[float | None] = mapped_column(Float)
    total_debt: Mapped[float | None] = mapped_column(Float)
    cash: Mapped[float | None] = mapped_column(Float)
    shareholders_equity: Mapped[float | None] = mapped_column(Float)

    # Cash flow
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    capital_expenditure: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index(
            "ix_financial_statements_company_period",
            "company_id",
            "period",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<FinancialStatement(company_id={self.company_id}, period={self.period!r})>"


class FinancialMetric(Base, TimestampMixin):
    """Derived financial ratios — calculated by Python, never by the LLM."""

    __tablename__ = "financial_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Valuation
    pe_ratio: Mapped[float | None] = mapped_column(Float)
    ps_ratio: Mapped[float | None] = mapped_column(Float)
    pb_ratio: Mapped[float | None] = mapped_column(Float)
    ev_ebitda: Mapped[float | None] = mapped_column(Float)

    # Profitability
    roe: Mapped[float | None] = mapped_column(Float)
    roa: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    operating_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)

    # Financial health
    debt_equity: Mapped[float | None] = mapped_column(Float)
    current_ratio: Mapped[float | None] = mapped_column(Float)
    fcf_yield: Mapped[float | None] = mapped_column(Float)

    # Growth
    revenue_growth: Mapped[float | None] = mapped_column(Float)
    earnings_growth: Mapped[float | None] = mapped_column(Float)
    fcf_growth: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_financial_metrics_company_ts", "company_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<FinancialMetric(company_id={self.company_id}, ts={self.timestamp})>"