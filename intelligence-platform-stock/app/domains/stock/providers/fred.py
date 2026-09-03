"""
FRED provider — primary macroeconomic data source.

Provides:
    - Interest rates (Fed Funds Rate, Treasury yields)
    - Inflation (CPI, PPI)
    - GDP
    - Unemployment
    - Money supply
    - Consumer sentiment
    - Industrial production
    - Housing

FRED requires an API key (free registration).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers.base import MacroDataProvider

logger = get_logger(__name__)
settings = get_stock_config()


# Common FRED indicator series IDs
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "ppi": "PPIACO",
    "gdp": "GDP",
    "real_gdp": "GDPC1",
    "unemployment_rate": "UNRATE",
    "treasury_3m": "DGS3MO",
    "treasury_2y": "DGS2",
    "treasury_10y": "DGS10",
    "treasury_30y": "DGS30",
    "money_supply_m2": "M2SL",
    "consumer_sentiment": "UMCSENT",
    "industrial_production": "INDPRO",
    "housing_starts": "HOUST",
    "vix": "VIXCLS",
}


class FREDProvider(MacroDataProvider):
    """
    FRED (Federal Reserve Economic Data) adapter.

    Source_docs.md §6:
        FRED is operated by the Federal Reserve Bank of St. Louis.
        Provides programmatic access to economic data.
        Requires API key (free registration).
    """

    provider_name = "fred"
    base_url = settings.FRED_BASE_URL
    rate_limit_per_sec = 5  # FRED allows 120 req/min = 2/sec, being conservative

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key or settings.FRED_API_KEY)

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._build_params(**kwargs)
        if self.api_key:
            params["api_key"] = self.api_key
        params["file_type"] = "json"
        return params

    # -- Generic Provider Protocol (Section 6) ----------------------

    async def fetch(self, entity_ref) -> list[dict[str, Any]]:
        """Generic fetch -- returns macro observations (entity-independent)."""
        results: list[dict[str, Any]] = []
        for name in FRED_SERIES:
            try:
                obs = await self.get_indicator(name)
                results.append({"kind": "macro", "data": obs[-5:] if obs else []})
            except Exception:
                logger.warning("FRED get_indicator(%s) failed", name, exc_info=True)
        return results


    async def get_indicator(self, indicator_id: str) -> list[dict[str, Any]]:
        """
        Get all observations for a FRED series.

        Endpoint: /series/observations?series_id={id}
        """
        series_id = FRED_SERIES.get(indicator_id, indicator_id)
        data = await self._request(
            "GET",
            "/series/observations",
            params=self._build_params(series_id=series_id),
            use_cache=False,
        )
        return self._parse_observations(data, indicator_id)

    async def get_indicator_series(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """Get observations for a date range."""
        series_id = FRED_SERIES.get(indicator_id, indicator_id)
        data = await self._request(
            "GET",
            "/series/observations",
            params=self._build_params(
                series_id=series_id,
                observation_start=start_date.strftime("%Y-%m-%d"),
                observation_end=end_date.strftime("%Y-%m-%d"),
            ),
            use_cache=False,
        )
        return self._parse_observations(data, indicator_id)

    async def get_series_info(self, indicator_id: str) -> dict[str, Any]:
        """Get metadata about a FRED series."""
        series_id = FRED_SERIES.get(indicator_id, indicator_id)
        return await self._request(
            "GET",
            "/series",
            params=self._build_params(series_id=series_id),
        )

    async def get_all_indicators(self) -> dict[str, list[dict[str, Any]]]:
        """Fetch all configured macro indicators."""
        results: dict[str, list[dict[str, Any]]] = {}
        for name in FRED_SERIES:
            try:
                results[name] = await self.get_indicator(name)
            except Exception as exc:
                logger.error("Failed to fetch FRED indicator %s: %s", name, exc)
                results[name] = []
        return results

    @staticmethod
    def _parse_observations(data: dict[str, Any], indicator_id: str) -> list[dict[str, Any]]:
        observations = data.get("observations", [])
        return [
            {
                "indicator": indicator_id,
                "timestamp": obs.get("date"),
                "value": float(obs["value"]) if obs.get("value", ".") != "." else None,
                "source": "FRED",
                "frequency": data.get("frequency", ""),
                "unit": data.get("units", ""),
            }
            for obs in observations
            if obs.get("value", ".") != "."
        ]
