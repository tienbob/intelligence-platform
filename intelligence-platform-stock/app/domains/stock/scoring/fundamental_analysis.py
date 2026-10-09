"""
Fundamental analysis engine (Section 20).

Deterministic calculation of financial ratios and growth metrics.
The LLM must NOT calculate these values itself.

Calculates:
    Revenue Growth, EPS Growth, FCF Growth,
    Gross Margin, Operating Margin, Net Margin,
    ROE, ROA, Debt/Equity, Current Ratio,
    P/E, P/S, P/B, EV/EBITDA, FCF Yield
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.database import commit_session
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement

logger = get_logger(__name__)


class FundamentalAnalysisEngine:
    """
    Calculates financial ratios and growth metrics from financial statements.

    All calculations are deterministic — no LLM involvement.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_statements(
        self, company_id: int, limit: int = 8
    ) -> list[FinancialStatement]:
        """Load recent financial statements (quarterly)."""
        result = await self.session.execute(
            select(FinancialStatement)
            .where(FinancialStatement.company_id == company_id)
            .where(FinancialStatement.period_type == "quarterly")
            .order_by(desc(FinancialStatement.period))
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    @staticmethod
    def _safe_divide(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return a / b

    @staticmethod
    def _growth_rate(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / abs(previous)

    def calculate_metrics(
        self, statements: list[FinancialStatement]
    ) -> dict[str, float | None]:
        """Calculate all fundamental metrics from statements."""
        if not statements:
            return {}

        latest = statements[-1]
        prev = statements[-2] if len(statements) >= 2 else None
        year_ago = statements[-5] if len(statements) >= 5 else None

        metrics: dict[str, float | None] = {}

        # Profitability
        metrics["gross_margin"] = self._safe_divide(latest.gross_profit, latest.revenue)
        metrics["operating_margin"] = self._safe_divide(latest.operating_income, latest.revenue)
        metrics["net_margin"] = self._safe_divide(latest.net_income, latest.revenue)

        # Returns
        metrics["roe"] = self._safe_divide(latest.net_income, latest.shareholders_equity)
        metrics["roa"] = self._safe_divide(latest.net_income, latest.total_assets)

        # Financial health
        metrics["debt_equity"] = self._safe_divide(latest.total_debt, latest.shareholders_equity)
        # Current ratio requires current_assets / current_liabilities, which are
        # not available in the FinancialStatement model. Set to None rather than
        # computing a meaningless approximation (cash / total_liabilities).
        metrics["current_ratio"] = None
        metrics["fcf_yield"] = self._safe_divide(latest.free_cash_flow, latest.revenue)

        # Growth (YoY)
        if year_ago:
            metrics["revenue_growth"] = self._growth_rate(latest.revenue, year_ago.revenue)
            metrics["earnings_growth"] = self._growth_rate(latest.net_income, year_ago.net_income)
            metrics["fcf_growth"] = self._growth_rate(latest.free_cash_flow, year_ago.free_cash_flow)
        else:
            metrics["revenue_growth"] = None
            metrics["earnings_growth"] = None
            metrics["fcf_growth"] = None

        # Valuation (requires market data — would be set from price * shares)
        # These are placeholders; in production, fetch from market data
        metrics["pe_ratio"] = None  # Set from price / EPS
        metrics["ps_ratio"] = None  # Set from market_cap / revenue
        metrics["pb_ratio"] = None  # Set from market_cap / equity
        metrics["ev_ebitda"] = None  # Set from EV / EBITDA

        return metrics

    async def calculate_and_store(self, company_id: int) -> FinancialMetric | None:
        """Calculate metrics and store in the database."""
        statements = await self._load_statements(company_id)
        if not statements:
            logger.warning("No financial statements for company_id=%d", company_id)
            return None

        metrics = self.calculate_metrics(statements)

        metric = FinancialMetric(
            company_id=company_id,
            timestamp=datetime.now(timezone.utc),
            **metrics,
        )
        self.session.add(metric)
        await commit_session(self.session)
        logger.info("Calculated fundamental metrics for company_id=%d", company_id)
        return metric

    async def get_latest_metrics(self, company_id: int) -> FinancialMetric | None:
        """Get the most recent financial metrics."""
        result = await self.session.execute(
            select(FinancialMetric)
            .where(FinancialMetric.company_id == company_id)
            .order_by(desc(FinancialMetric.timestamp))
            .limit(1)
        )
        return result.scalar_one_or_none()