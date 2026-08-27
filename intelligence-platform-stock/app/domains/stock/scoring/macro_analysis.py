"""
Macro analysis engine (Section 21).

Uses FRED and other macro providers to calculate:
    Interest-rate environment, Inflation trend, GDP growth,
    Unemployment, Treasury yield environment,
    Economic expansion/contraction
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.macro import EconomicIndicator

logger = get_logger(__name__)


class MacroAnalysisEngine:
    """Analyzes macroeconomic environment from stored indicators."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_latest_value(self, indicator: str) -> tuple[float | None, datetime | None]:
        """Get the latest value and timestamp for an indicator."""
        result = await self.session.execute(
            select(EconomicIndicator)
            .where(EconomicIndicator.indicator == indicator)
            .order_by(desc(EconomicIndicator.timestamp))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            return row.value, row.timestamp
        return None, None

    async def _get_series(self, indicator: str, days: int = 365) -> list[EconomicIndicator]:
        """Get a time series for an indicator."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(EconomicIndicator)
            .where(EconomicIndicator.indicator == indicator)
            .where(EconomicIndicator.timestamp >= since)
            .order_by(EconomicIndicator.timestamp)
        )
        return list(result.scalars().all())

    async def get_macro_snapshot(self) -> dict[str, Any]:
        """
        Build a macro environment snapshot for LLM context.

        Section 21: The macro environment should become part of company analysis.
        """
        snapshot: dict[str, Any] = {}

        # Interest rates
        fed_rate, fed_rate_date = await self._get_latest_value("fed_funds_rate")
        snapshot["fed_funds_rate"] = fed_rate
        snapshot["fed_funds_rate_date"] = fed_rate_date.isoformat() if fed_rate_date else None

        # Treasury yields
        for maturity in ["treasury_3m", "treasury_2y", "treasury_10y", "treasury_30y"]:
            val, dt = await self._get_latest_value(maturity)
            snapshot[maturity] = val

        # Yield curve slope (10Y - 2Y)
        if snapshot.get("treasury_10y") and snapshot.get("treasury_2y"):
            snapshot["yield_curve_slope"] = snapshot["treasury_10y"] - snapshot["treasury_2y"]
            snapshot["yield_curve_inverted"] = snapshot["yield_curve_slope"] < 0
        else:
            snapshot["yield_curve_slope"] = None
            snapshot["yield_curve_inverted"] = None

        # Inflation — compute YoY% change from CPI index
        # Get latest CPI, then find value from ~12 months prior
        cpi_series = await self._get_series("cpi", days=500)
        if len(cpi_series) >= 2:
            latest = cpi_series[-1]
            # Find the observation closest to 12 months before the latest
            target_date = latest.timestamp - timedelta(days=365)
            year_ago = min(cpi_series, key=lambda x: abs((x.timestamp - target_date).total_seconds()))
            if latest.value and year_ago.value and year_ago.value != 0:
                snapshot["cpi"] = round((latest.value - year_ago.value) / year_ago.value * 100, 1)
            else:
                snapshot["cpi"] = latest.value
        else:
            cpi, _ = await self._get_latest_value("cpi")
            snapshot["cpi"] = cpi

        # GDP
        gdp, gdp_date = await self._get_latest_value("gdp")
        snapshot["gdp"] = gdp

        # Unemployment
        unemployment, _ = await self._get_latest_value("unemployment_rate")
        snapshot["unemployment_rate"] = unemployment

        # VIX
        vix, _ = await self._get_latest_value("vix")
        snapshot["vix"] = vix

        # Determine economic regime
        snapshot["economic_regime"] = self._classify_regime(snapshot)

        # Economic trend derived from the available macro signals.
        # This is intentionally separate from regime so callers can
        # distinguish "data says neutral" from "no data available".
        snapshot["economic_trend"] = self._derive_trend(snapshot)

        return snapshot

    @staticmethod
    def _has_any_signal(snapshot: dict[str, Any]) -> bool:
        """Return True when any meaningful macro signal is present."""
        return any(
            snapshot.get(k) is not None
            for k in (
                "fed_funds_rate",
                "yield_curve_inverted",
                "unemployment_rate",
                "vix",
                "cpi",
                "gdp",
            )
        )

    @classmethod
    def _classify_regime(cls, snapshot: dict[str, Any]) -> str:
        """
        Classify the macro environment into a regime.

        Returns one of: expansion, contraction_risk, high_volatility,
        neutral, or unknown.

        "unknown" means insufficient data to make a determination —
        it must never be confused with a genuinely neutral regime.

        These values are consumed by market.py to derive trend/risk_level.
        """
        fed_rate = snapshot.get("fed_funds_rate")
        yield_inverted = snapshot.get("yield_curve_inverted")
        unemployment = snapshot.get("unemployment_rate")
        vix = snapshot.get("vix")

        # High volatility overrides everything — panic mode.
        if vix is not None and vix > 30:
            return "high_volatility"

        # Contraction signals: inverted yield curve or restrictive monetary policy.
        if yield_inverted:
            return "contraction_risk"
        if fed_rate is not None and fed_rate > 5:
            return "contraction_risk"

        # Expansion: tight labor market.
        if unemployment is not None and unemployment < 4:
            return "expansion"

        # If we have at least one real signal and none of the above fired,
        # the environment is genuinely neutral.
        if cls._has_any_signal(snapshot):
            return "neutral"

        # No data at all → unknown, not neutral.
        return "unknown"

    @staticmethod
    def _derive_trend(snapshot: dict[str, Any]) -> str:
        """Derive an economic trend from macro signals; returns 'unknown' when data is missing."""
        regime = snapshot.get("economic_regime")
        if regime == "expansion":
            return "bullish"
        if regime in ("contraction_risk", "high_volatility"):
            return "bearish"
        if regime == "unknown":
            return "unknown"
        return "neutral"

    async def get_trend(self, indicator: str, days: int = 90) -> dict[str, Any]:
        """Calculate trend for a specific indicator."""
        series = await self._get_series(indicator, days)
        if len(series) < 2:
            return {"trend": "unknown", "change": None}

        values = [s.value for s in series if s.value is not None]
        if len(values) < 2:
            return {"trend": "unknown", "change": None}

        change = values[-1] - values[0]
        pct_change = (change / values[0] * 100) if values[0] != 0 else None

        if change > 0:
            trend = "rising"
        elif change < 0:
            trend = "falling"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "change": change,
            "percent_change": pct_change,
            "latest": values[-1],
            "earliest": values[0],
        }