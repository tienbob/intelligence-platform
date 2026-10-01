"""
Risk engine (Section 33).

The risk engine operates independently from the LLM.

Calculates:
    Volatility, Beta, Maximum Drawdown, Value-at-Risk,
    Liquidity, Fundamental Risk, Event Risk,
    Concentration Risk, Sector Risk, Correlation Risk

Output:
    {
        "risk_score": 34,
        "volatility": 0.21,
        "max_drawdown": 0.18,
        "event_risk": 0.32,
        "fundamental_risk": 0.24,
        "confidence": 0.87
    }
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_session
from app.core.logging import get_logger
from app.domains.stock.models.analysis import RiskMetric
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.financial import FinancialStatement
from app.domains.stock.models.stock_price import StockPrice

logger = get_logger(__name__)


class RiskEngine:
    """
    Calculates risk metrics independently from the LLM.

    Section 33: The risk engine should operate independently from the LLM.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_prices(self, company_id: int, days: int = 252) -> pd.DataFrame:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= since)
            .order_by(StockPrice.timestamp)
        )
        prices = result.scalars().all()
        if not prices:
            return pd.DataFrame()
        df = pd.DataFrame([
            {"date": p.timestamp, "close": p.close, "volume": p.volume}
            for p in prices
        ])
        df.set_index("date", inplace=True)
        return df

    @staticmethod
    def _volatility(returns: pd.Series) -> float | None:
        """Annualized volatility."""
        if len(returns) < 20:
            return None
        return float(returns.std() * np.sqrt(252))

    @staticmethod
    def _max_drawdown(prices: pd.Series) -> float | None:
        """Maximum drawdown (positive magnitude, e.g. 0.18 for 18%)."""
        if len(prices) < 2:
            return None
        running_max = prices.cummax()
        drawdown = (prices - running_max) / running_max
        return float(abs(drawdown.min()))

    @staticmethod
    def _value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float | None:
        """Value at Risk (VaR) at given confidence level."""
        if len(returns) < 30:
            return None
        return float(np.percentile(returns, (1 - confidence) * 100))

    @staticmethod
    def _liquidity_score(volumes: pd.Series) -> float | None:
        """Liquidity score based on average volume (0-1, higher = more liquid)."""
        if len(volumes) < 20:
            return None
        avg_vol = volumes.tail(20).mean()
        # $10M+ daily volume = 1.0, $1M = 0.5, <$100K = 0.1
        # Assuming avg price ~$50, so volume * 50 = notional
        if avg_vol <= 0:
            return 0.0
        score = min(1.0, np.log10(avg_vol) / 7)  # 10M = 1.0
        return float(max(0, score))

    async def _fundamental_risk(self, company_id: int) -> float | None:
        """Assess fundamental risk from financial statements."""
        result = await self.session.execute(
            select(FinancialStatement)
            .where(FinancialStatement.company_id == company_id)
            .order_by(desc(FinancialStatement.period))
            .limit(1)
        )
        stmt = result.scalar_one_or_none()
        if not stmt:
            return None

        risk = 0.5  # Base

        # High debt/equity increases risk
        if stmt.shareholders_equity and stmt.total_debt:
            de_ratio = stmt.total_debt / stmt.shareholders_equity
            if de_ratio > 2:
                risk += 0.2
            elif de_ratio > 1:
                risk += 0.1

        # Negative net income increases risk
        if stmt.net_income and stmt.net_income < 0:
            risk += 0.15

        # Negative FCF increases risk
        if stmt.free_cash_flow and stmt.free_cash_flow < 0:
            risk += 0.1

        return float(min(1.0, risk))

    async def _event_risk(self, company_id: int) -> float | None:
        """Assess event risk from recent events."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        result = await self.session.execute(
            select(MarketEvent)
            .where(MarketEvent.company_id == company_id)
            .where(MarketEvent.event_date >= since)
        )
        events = result.scalars().all()

        if not events:
            return 0.1  # Low event risk

        negative_events = [e for e in events if e.impact == "negative"]
        risk = min(1.0, 0.1 + len(negative_events) * 0.15)
        return float(risk)

    @staticmethod
    def _beta(returns: pd.Series, market_returns: pd.Series | None = None) -> float | None:
        """
        Calculate beta (Section 33).
        
        If market benchmark returns are available, compute standard beta via
        covariance / variance.  Falls back to an autocorrelation-based
        estimate when no benchmark is provided.
        """
        if len(returns) < 30:
            return None

        if market_returns is not None and len(market_returns) >= 30:
            # Standard beta = Cov(R_stock, R_market) / Var(R_market)
            aligned = pd.concat([returns, market_returns], axis=1).dropna()
            if len(aligned) >= 30:
                cov = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
                var = aligned.iloc[:, 1].var()
                if var > 0:
                    return float(cov / var)
            return None

        # Fallback: autocorrelation-based beta proxy
        # Higher serial correlation ≈ higher persistence ≈ higher beta
        lag1 = returns.autocorr(lag=1)
        if lag1 is None or np.isnan(lag1):
            return None
        # Map autocorrelation (-1..1) to beta (0..2)
        return float(max(0.1, min(2.0, 1.0 + lag1)))

    @staticmethod
    def _concentration_risk(volatility: float | None) -> float | None:
        """
        Concentration risk for single-company context (Section 33).

        For a single stock, higher volatility implies higher concentration
        and tail-risk exposure.  Scaled to 0-1.
        """
        if volatility is None:
            return None
        # Annualized volatility > 60% = high concentration risk
        return float(min(1.0, max(0.0, volatility / 0.60)))

    async def _sector_risk(self, company_id: int) -> float | None:
        """
        Sector risk (Section 33).

        Estimates sector-related risk from the company's beta and fundamental risk.
        Without portfolio-level sector data, we proxy sector risk from the
        stock's own volatility characteristics.
        """
        # This would ideally pull sector-level data; for now derive from
        # the company's own risk profile.
        stmt_result = await self.session.execute(
            select(FinancialStatement)
            .where(FinancialStatement.company_id == company_id)
            .order_by(desc(FinancialStatement.period))
            .limit(1)
        )
        stmt = stmt_result.scalar_one_or_none()
        if not stmt:
            return None

        risk = 0.3  # Base sector risk

        # High debt increases sector sensitivity
        if stmt.total_debt and stmt.shareholders_equity and stmt.total_debt > 0:
            de = stmt.total_debt / stmt.shareholders_equity
            if de > 2:
                risk += 0.3
            elif de > 1:
                risk += 0.15

        return float(min(1.0, risk))

    @staticmethod
    def _correlation_risk(returns: pd.Series) -> float | None:
        """
        Correlation risk (Section 33).

        Measures autocorrelation in daily returns — high serial correlation
        indicates trending behaviour and elevated correlation risk.
        Scaled to 0-1.
        """
        if len(returns) < 30:
            return None
        ac = returns.autocorr(lag=1)
        if ac is None or np.isnan(ac):
            return None
        # |autocorrelation| of 0 = 0 risk, 0.3+ = high risk
        return float(min(1.0, abs(ac) / 0.3))

    async def calculate_risk(self, company_id: int) -> RiskMetric | None:
        """Calculate all risk metrics and store in DB."""
        df = await self._load_prices(company_id)
        if df.empty or len(df) < 20:
            logger.warning("Insufficient data for risk calculation: company_id=%d", company_id)
            return None

        returns = df["close"].pct_change().dropna()

        volatility = self._volatility(returns)
        max_dd = self._max_drawdown(df["close"])
        var = self._value_at_risk(returns)
        liquidity = self._liquidity_score(df["volume"])
        fund_risk = await self._fundamental_risk(company_id)
        evt_risk = await self._event_risk(company_id)
        beta = self._beta(returns)
        conc_risk = self._concentration_risk(volatility)
        sec_risk = await self._sector_risk(company_id)
        corr_risk = self._correlation_risk(returns)

        # Overall risk score (0-100, higher = riskier)
        # max_drawdown is positive magnitude (e.g. 0.18 for 18% drawdown)
        risk_components = [
            v for v in [volatility, max_dd, fund_risk, evt_risk] if v is not None
        ]
        if risk_components:
            # Each component is 0-1 scale; average and scale to 0-100, clamp
            risk_score = float(min(100.0, max(0.0, np.mean(risk_components) * 100)))
        else:
            risk_score = 50.0

        # Confidence based on data availability
        confidence = min(1.0, len(df) / 252)

        metric = RiskMetric(
            company_id=company_id,
            timestamp=datetime.now(timezone.utc),
            risk_score=risk_score,
            volatility=volatility,
            beta=beta,
            max_drawdown=max_dd,
            value_at_risk=var,
            liquidity_score=liquidity,
            fundamental_risk=fund_risk,
            event_risk=evt_risk,
            concentration_risk=conc_risk,
            sector_risk=sec_risk,
            correlation_risk=corr_risk,
            confidence=confidence,
        )
        self.session.add(metric)
        await commit_session(self.session)
        logger.info("Calculated risk metrics for company_id=%d: score=%.1f", company_id, risk_score)
        return metric

    async def get_latest_risks(self, company_ids: list[int]) -> dict[int, RiskMetric]:
        """Fetch one deterministic latest row per requested company in one query."""
        if not company_ids:
            return {}
        result = await self.session.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id.in_(set(company_ids)))
            .distinct(RiskMetric.company_id)
            .order_by(RiskMetric.company_id, RiskMetric.timestamp.desc(), RiskMetric.id.desc())
        )
        return {row.company_id: row for row in result.scalars().all()}

    async def get_latest_risk(self, company_id: int) -> RiskMetric | None:
        """Get the most recent risk metrics."""
        result = await self.session.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company_id)
            .order_by(desc(RiskMetric.timestamp), desc(RiskMetric.id))
            .limit(1)
        )
        return result.scalar_one_or_none()