"""
Massive (formerly Polygon.io) provider — primary market-data provider.

Provides:
    - Stock prices / OHLCV
    - Market movers
    - Company news
    - Financial statements
    - Ratios
    - Short interest
    - Corporate actions
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers.base import (
    FundamentalDataProvider,
    MarketDataProvider,
    NewsProvider,
)

logger = get_logger(__name__)
settings = get_stock_config()


class MassiveProvider(MarketDataProvider, NewsProvider, FundamentalDataProvider):
    """
    Massive adapter implementing market-data, news, and fundamental interfaces.

    Endpoint reference:
        Market Data:
            GET /v2/aggs/ticker/{ticker}/range/...
            GET /v2/reference/news
            GET /v2/snapshot/locale/us/markets/stocks/gainers
            GET /v2/snapshot/locale/us/markets/stocks/losers
        Fundamentals:
            GET /stocks/financials/v1/income-statements
            GET /stocks/financials/v1/balance-sheets
            GET /stocks/financials/v1/cash-flow-statements
    """

    provider_name = "massive"
    base_url = settings.MASSIVE_BASE_URL
    rate_limit_per_sec = settings.MASSIVE_RATE_LIMIT

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key or settings.MASSIVE_API_KEY)

    def _get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._build_params(**kwargs)
        if self.api_key:
            params["apiKey"] = self.api_key
        return params

    # ── MarketDataProvider ───────────────────────────────────────

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        """Get latest quote via snapshot endpoint."""
        data = await self._request(
            "GET",
            f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params=self._build_params(),
        )
        snapshot = data.get("ticker", data)
        return {
            "ticker": ticker,
            "price": snapshot.get("lastTrade", {}).get("p") or snapshot.get("close", 0),
            "change": snapshot.get("todaysChange", 0),
            "change_percent": snapshot.get("todaysChangePerc", 0),
            "volume": snapshot.get("day", {}).get("v", 0),
                "timestamp": self._normalize_timestamp(snapshot.get("updated")),
        }

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        """Get historical OHLCV via aggregates endpoint."""
        # Map interval to multiplier + timespan
        interval_map = {
            "1m": (1, "minute"),
            "5m": (5, "minute"),
            "15m": (15, "minute"),
            "1h": (1, "hour"),
            "1d": (1, "day"),
            "1W": (1, "week"),
            "1M": (1, "month"),
        }
        multiplier, timespan = interval_map.get(interval, (1, "day"))

        params = self._build_params(
            adjusted="true",
            sort="asc",
            **({"limit": 50000} if interval in ("1d", "1W", "1M") else {"limit": 5000}),
        )

        data = await self._request(
            "GET",
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}",
            params=params,
        )

        results = data.get("results", [])
        return [
            {
                "timestamp": self._normalize_timestamp(r.get("t")),
                "open": r.get("o"),
                "high": r.get("h"),
                "low": r.get("l"),
                "close": r.get("c"),
                "adjusted_close": r.get("c"),  # adjusted=true already adjusts
                "volume": r.get("v", 0),
            }
            for r in results
        ]

    async def get_market_movers(self) -> dict[str, list[dict[str, Any]]]:
        """Get top gainers and losers."""
        gainers_data = await self._request(
            "GET",
            "/v2/snapshot/locale/us/markets/stocks/gainers",
            params=self._build_params(),
        )
        losers_data = await self._request(
            "GET",
            "/v2/snapshot/locale/us/markets/stocks/losers",
            params=self._build_params(),
        )

        def parse_movers(data: dict) -> list[dict[str, Any]]:
            return [
                {
                    "ticker": m.get("ticker"),
                    "price": m.get("day", {}).get("c", 0),
                    "change_percent": m.get("todaysChangePerc", 0),
                    "volume": m.get("day", {}).get("v", 0),
                }
                for m in data.get("tickers", [])
            ]

        return {
            "gainers": parse_movers(gainers_data),
            "losers": parse_movers(losers_data),
        }

    # ── NewsProvider ─────────────────────────────────────────────

    async def search_news(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/v2/reference/news",
            params=self._build_params(q=query, order="desc", limit=limit),
        )
        return self._parse_news(data.get("results", []))

    async def get_company_news(self, ticker: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/v2/reference/news",
            params=self._build_params(ticker=ticker, order="desc", limit=limit),
        )
        return self._parse_news(data.get("results", []))

    @staticmethod
    def _parse_news(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "external_id": str(r.get("id", "")),
                "source": "massive",
                "title": r.get("title", ""),
                "url": r.get("article_url"),
                "published_at": r.get("published_utc"),
                "summary": r.get("description"),
                "content": None,  # No content extraction implemented; summary is used
                "tickers": [
                    t if isinstance(t, str) else t.get("ticker")
                    for t in r.get("tickers", [])
                    if (isinstance(t, str) and t) or (isinstance(t, dict) and t.get("ticker"))
                ],
                "sentiment": r.get("sentiment"),
            }
            for r in results
        ]

    # ── FundamentalDataProvider ──────────────────────────────────

    async def get_ticker_details(self, ticker: str) -> dict[str, Any]:
        """Get ticker/company details (name, exchange, market cap).

        Endpoint: GET /v3/reference/tickers/{ticker}
        """
        data = await self._request(
            "GET",
            f"/v3/reference/tickers/{ticker.upper()}",
            params=self._build_params(),
        )
        return data.get("results", data) if isinstance(data, dict) else {}

    async def get_income_statement(self, ticker: str) -> list[dict[str, Any]]:
        """
        Get income statement data.
        
        Endpoint: GET /stocks/financials/v1/income-statements
        """
        params = self._build_params(ticker=ticker)
        data = await self._request(
            "GET",
            "/stocks/financials/v1/income-statements",
            params=params,
        )
        return data.get("results", [])

    async def get_balance_sheet(self, ticker: str) -> list[dict[str, Any]]:
        """
        Get balance sheet data.
        
        Endpoint: GET /stocks/financials/v1/balance-sheets
        """
        params = self._build_params(ticker=ticker)
        data = await self._request(
            "GET",
            "/stocks/financials/v1/balance-sheets",
            params=params,
        )
        return data.get("results", [])

    async def get_cash_flow(self, ticker: str) -> list[dict[str, Any]]:
        """
        Get cash flow statement data.
        
        Endpoint: GET /stocks/financials/v1/cash-flow-statements
        """
        params = self._build_params(ticker=ticker)
        data = await self._request(
            "GET",
            "/stocks/financials/v1/cash-flow-statements",
            params=params,
        )
        return data.get("results", [])

