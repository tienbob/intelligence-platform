"""
Financial Modeling Prep (FMP) provider — normalized financial data.

Provides:
    - Income statements
    - Balance sheets
    - Cash flow statements
    - Ratios
    - Historical prices
    - Company information
    - Enterprise value

FMP is the most convenient provider for normalized financial data.

The current FMP API uses the /stable/ base with query-parameter style
calls (e.g. /quote?symbol=AAPL), replacing the legacy /api/v3 path-style
endpoints (e.g. /quote/{ticker}).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers.base import (
    FundamentalDataProvider,
    MarketDataProvider,
)

logger = get_logger(__name__)
settings = get_stock_config()


class FMPProvider(FundamentalDataProvider, MarketDataProvider):
    """
    FMP adapter implementing fundamental and market-data interfaces.

    Source_docs.md §3:
        FMP is the most convenient provider for normalized financial data.
        Endpoints:
            /stable/quote?symbol=AAPL
            /stable/income-statement?symbol=AAPL
            /stable/balance-sheet-statement?symbol=AAPL
            /stable/cash-flow-statement?symbol=AAPL
    """

    provider_name = "fmp"
    base_url = settings.FMP_BASE_URL
    rate_limit_per_sec = 5

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key or settings.FMP_API_KEY)

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._build_params(**kwargs)
        if self.api_key:
            params["apikey"] = self.api_key
        return params

    # ── FundamentalDataProvider ──────────────────────────────────

    async def get_income_statement(self, ticker: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/income-statement",
            params=self._build_params(symbol=ticker, period="quarter"),
        )
        return self._normalize_income(data if isinstance(data, list) else data.get("results", []))

    async def get_balance_sheet(self, ticker: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/balance-sheet-statement",
            params=self._build_params(symbol=ticker, period="quarter"),
        )
        return self._normalize_balance(data if isinstance(data, list) else data.get("results", []))

    async def get_cash_flow(self, ticker: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/cash-flow-statement",
            params=self._build_params(symbol=ticker, period="quarter"),
        )
        return self._normalize_cashflow(data if isinstance(data, list) else data.get("results", []))

    async def get_ratios(self, ticker: str) -> list[dict[str, Any]]:
        """Get financial ratios (P/E, P/S, ROE, etc.)."""
        data = await self._request(
            "GET",
            "/ratios",
            params=self._build_params(symbol=ticker, period="quarter"),
        )
        return data if isinstance(data, list) else data.get("results", [])

    async def get_company_profile(self, ticker: str) -> dict[str, Any]:
        """Get company profile / information."""
        data = await self._request(
            "GET",
            "/profile",
            params=self._build_params(symbol=ticker),
        )
        profiles = data if isinstance(data, list) else data.get("results", [])
        return profiles[0] if profiles else {}

    async def get_enterprise_value(self, ticker: str) -> list[dict[str, Any]]:
        """Get enterprise value data."""
        data = await self._request(
            "GET",
            "/enterprise-values",
            params=self._build_params(symbol=ticker, period="quarter"),
        )
        return data if isinstance(data, list) else data.get("enterpriseValues", data.get("results", []))

    # ── MarketDataProvider ───────────────────────────────────────

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._request(
            "GET",
            "/quote",
            params=self._build_params(symbol=ticker),
        )
        quotes = data if isinstance(data, list) else data.get("quotes", data.get("results", []))
        if not quotes:
            return {"ticker": ticker, "price": 0, "change": 0, "change_percent": 0, "volume": 0}
        q = quotes[0] if isinstance(quotes, list) else quotes
        return {
            "ticker": q.get("symbol", ticker),
            "name": q.get("name", ""),
            "price": q.get("price", 0),
            "change": q.get("change", 0),
            "change_percent": q.get("changesPercentage", 0),
            "volume": q.get("volume", 0),
            "timestamp": self._normalize_timestamp(q.get("timestamp")),
        }

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        # FMP uses /historical-price-full/{ticker}?from=...&to=...
        # On the stable API: /historical-price-eod/full?symbol=AAPL&from=...&to=...
        data = await self._request(
            "GET",
            "/historical-price-eod/full",
            params=self._build_params(
                **{
                    "symbol": ticker,
                    "from": start_date.strftime("%Y-%m-%d"),
                    "to": end_date.strftime("%Y-%m-%d"),
                }
            ),
        )
        historical = data if isinstance(data, list) else data.get("historical", [])
        return [
            {
                "timestamp": self._normalize_timestamp(h.get("date")),
                "open": h.get("open"),
                "high": h.get("high"),
                "low": h.get("low"),
                "close": h.get("close"),
                "adjusted_close": h.get("adjClose", h.get("close")),
                "volume": h.get("volume", 0),
            }
            for h in reversed(historical)  # FMP returns newest first
        ]

    async def get_market_movers(self) -> dict[str, list[dict[str, Any]]]:
        gainers = await self._request("GET", "/stock_market/gainers", params=self._build_params())
        losers = await self._request("GET", "/stock_market/losers", params=self._build_params())

        def parse(data: dict) -> list[dict[str, Any]]:
            items = data if isinstance(data, list) else data.get("mostGainerStock", data.get("mostLoserStock", []))
            return [
                {
                    "ticker": m.get("symbol"),
                    "name": m.get("name"),
                    "price": m.get("price", 0),
                    "change_percent": m.get("changesPercentage", 0),
                    "volume": m.get("volume", 0),
                }
                for m in items
            ]

        return {"gainers": parse(gainers), "losers": parse(losers)}

    # ── Normalization helpers ────────────────────────────────────

    @staticmethod
    def _detect_period_type(period: str) -> str:
        """Detect quarterly vs annual from a period string.

        FMP period strings are dates like '2026-06-30'. Quarterly periods
        are detected by the API's ``period`` query param (quarter), but the
        normalized output uses the date. We detect quarter by checking if
        the month is a quarter-end month (03, 06, 09, 12) — but that's
        ambiguous for annual (also ends in 12). Instead, use the FMP
        ``period`` field when present (e.g. 'Q1', 'Q2', 'FY').
        """
        p = str(period or "").upper()
        # Explicit quarter markers
        if "Q" in p and not p.startswith("FY"):
            return "quarterly"
        # Explicit annual markers
        if p.startswith("FY") or p.endswith("Y"):
            return "annual"
        # Date-based fallback: quarter-end months (03, 06, 09) are quarterly;
        # December could be either, default to annual for year-end.
        import re
        m = re.search(r"-(\d{2})-", p)
        if m:
            month = m.group(1)
            if month in ("03", "06", "09"):
                return "quarterly"
        return "annual"

    @staticmethod
    def _normalize_income(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "period": r.get("date", ""),
                "period_type": FMPProvider._detect_period_type(r.get("period", r.get("date", ""))),
                "currency": r.get("reportedCurrency", "USD"),
                "revenue": r.get("revenue"),
                "gross_profit": r.get("grossProfit"),
                "operating_income": r.get("operatingIncome"),
                "net_income": r.get("netIncome"),
                "eps": r.get("eps"),
                "source": "FMP",
                "source_id": r.get("link"),
                "filed_date": r.get("fillingDate"),
            }
            for r in raw
        ]

    @staticmethod
    def _normalize_balance(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "period": r.get("date", ""),
                "period_type": FMPProvider._detect_period_type(r.get("period", r.get("date", ""))),
                "currency": r.get("reportedCurrency", "USD"),
                "total_assets": r.get("totalAssets"),
                "total_liabilities": r.get("totalLiabilities"),
                "total_debt": r.get("totalDebt"),
                "cash": r.get("cashAndCashEquivalents"),
                "shareholders_equity": r.get("totalStockholdersEquity"),
                "source": "FMP",
                "source_id": r.get("link"),
                "filed_date": r.get("fillingDate"),
            }
            for r in raw
        ]

    @staticmethod
    def _normalize_cashflow(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "period": r.get("date", ""),
                "period_type": FMPProvider._detect_period_type(r.get("period", r.get("date", ""))),
                "currency": r.get("reportedCurrency", "USD"),
                "operating_cash_flow": r.get("operatingCashFlow"),
                "capital_expenditure": r.get("capitalExpenditure"),
                "free_cash_flow": r.get("freeCashFlow"),
                "source": "FMP",
                "source_id": r.get("link"),
                "filed_date": r.get("fillingDate"),
            }
            for r in raw
        ]
