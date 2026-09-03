"""
Finnhub provider — additional intelligence provider.

Provides:
    - Insider transactions
    - Institutional / fund ownership
    - Economic calendar
    - IPO calendar
    - Company news
    - Alternative data
    - Real-time stock data
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers.base import (
    AlternativeDataProvider,
    MarketDataProvider,
    NewsProvider,
)

logger = get_logger(__name__)
settings = get_stock_config()


class FinnhubProvider(
    AlternativeDataProvider,
    NewsProvider,
    MarketDataProvider,
):
    """
    Finnhub adapter implementing alternative-data, news, and market-data interfaces.

    Source_docs.md §5:
        Finnhub covers real-time market data, global company fundamentals,
        economic data and alternative data.
    """

    provider_name = "finnhub"
    base_url = settings.FINNHUB_BASE_URL
    rate_limit_per_sec = 10

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key or settings.FINNHUB_API_KEY)

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._build_params(**kwargs)
        if self.api_key:
            params["token"] = self.api_key
        return params

    # -- Generic Provider Protocol (Section 6) ----------------------

    async def fetch(self, entity_ref) -> list[dict[str, Any]]:
        """Generic fetch -- returns observations with ``kind`` fields."""
        ticker = entity_ref.entity_id
        results: list[dict[str, Any]] = []

        try:
            quote = await self.get_quote(ticker)
            results.append({"kind": "price_quote", "data": quote})
        except Exception:
            logger.warning("Finnhub get_quote failed for %s", ticker, exc_info=True)

        try:
            news = await self.get_company_news(ticker, limit=20)
            results.append({"kind": "news", "data": news})
        except Exception:
            logger.warning("Finnhub get_company_news failed for %s", ticker, exc_info=True)

        try:
            insider = await self.get_insider_transactions(ticker)
            results.append({"kind": "insider", "data": insider})
        except Exception:
            logger.warning("Finnhub get_insider_transactions failed for %s", ticker, exc_info=True)

        try:
            inst = await self.get_institutional_ownership(ticker)
            results.append({"kind": "institutional", "data": inst})
        except Exception:
            logger.warning("Finnhub get_institutional_ownership failed for %s", ticker, exc_info=True)

        return results


    # ── AlternativeDataProvider ──────────────────────────────────

    async def get_insider_transactions(self, ticker: str) -> list[dict[str, Any]]:
        """Get insider transactions for a ticker."""
        data = await self._request(
            "GET",
            "/stock/insider-transactions",
            params=self._build_params(symbol=ticker),
        )
        return [
            {
                "ticker": ticker,
                "transaction_date": t.get("transactionDate"),
                "insider_name": t.get("name"),
                "transaction_type": t.get("transactionCode"),
                "shares": t.get("share"),
                "price": t.get("transactionPrice"),
                "value": t.get("value"),
                "ownership_change": t.get("change"),
                "source": "Finnhub",
            }
            for t in data.get("data", [])
        ]

    async def get_institutional_ownership(self, ticker: str) -> list[dict[str, Any]]:
        """Get fund / institutional ownership data."""
        data = await self._request(
            "GET",
            "/stock/fund-ownership",
            params=self._build_params(symbol=ticker),
        )
        return [
            {
                "ticker": ticker,
                "filing_date": o.get("filingDate"),
                "institution": o.get("name"),
                "shares": o.get("share"),
                "value": o.get("value"),
                "percent_change": o.get("change"),
                "source": "Finnhub",
            }
            for o in data.get("data", [])
        ]

    async def get_economic_calendar(
        self, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Get economic calendar events."""
        params = self._build_params()
        if start_date:
            params["from"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["to"] = end_date.strftime("%Y-%m-%d")
        data = await self._request("GET", "/calendar/economic", params=params)
        return data.get("economicCalendar", [])

    async def get_ipo_calendar(
        self, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> dict[str, Any]:
        """Get IPO calendar."""
        params = self._build_params()
        if start_date:
            params["from"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["to"] = end_date.strftime("%Y-%m-%d")
        return await self._request("GET", "/calendar/ipo", params=params)

    # ── NewsProvider ─────────────────────────────────────────────

    async def search_news(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search general news."""
        data = await self._request(
            "GET",
            "/news",
            params=self._build_params(category="general"),
        )
        # /news returns a dict with "news" key containing the list
        return self._parse_news(data.get("news", [])[:limit])

    async def get_company_news(
        self, ticker: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get company-specific news."""
        data = await self._request(
            "GET",
            "/company-news",
            params=self._build_params(
                symbol=ticker,
                **({"from": datetime.now(timezone.utc).strftime("%Y-%m-%d")} if not False else {}),
            ),
        )
        # /company-news returns a list directly, but handle both formats
        news_data = data if isinstance(data, list) else data.get("news", [])
        return self._parse_news(news_data[:limit])

    @staticmethod
    def _parse_news(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "external_id": str(r.get("id", "")),
                "source": "finnhub",
                "title": r.get("headline", ""),
                "url": r.get("url"),
                "published_at": r.get("datetime"),
                "summary": r.get("summary"),
                "content": r.get("summary"),
                "tickers": [r.get("related", "")] if r.get("related") else [],
                "sentiment": r.get("sentiment"),
            }
            for r in results
        ]

    # ── MarketDataProvider ───────────────────────────────────────

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._request(
            "GET",
            "/quote",
            params=self._build_params(symbol=ticker),
        )
        return {
            "ticker": ticker,
            "price": data.get("c", 0),
            "change": data.get("d", 0),
            "change_percent": data.get("dp", 0),
            "volume": 0,  # Finnhub quote doesn't include volume
            "timestamp": self._normalize_timestamp(data.get("t")),
        }

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        resolution_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "1d": "D", "1W": "W", "1M": "M"}
        resolution = resolution_map.get(interval, "D")

        data = await self._request(
            "GET",
            "/stock/candle",
            params=self._build_params(
                symbol=ticker,
                resolution=resolution,
                **({"from": int(start_date.timestamp())} if start_date else {}),
                **({"to": int(end_date.timestamp())} if end_date else {}),
            ),
        )

        if data.get("s") != "ok":
            return []

        timestamps = data.get("t", [])
        return [
            {
                "timestamp": self._normalize_timestamp(ts),
                "open": data["o"][i] if i < len(data.get("o", [])) else None,
                "high": data["h"][i] if i < len(data.get("h", [])) else None,
                "low": data["l"][i] if i < len(data.get("l", [])) else None,
                "close": data["c"][i] if i < len(data.get("c", [])) else None,
                "adjusted_close": data["c"][i] if i < len(data.get("c", [])) else None,
                "volume": data["v"][i] if i < len(data.get("v", [])) else 0,
            }
            for i, ts in enumerate(timestamps)
        ]

    async def get_market_movers(self) -> dict[str, list[dict[str, Any]]]:
        # Finnhub doesn't have a direct movers endpoint; return empty
        return {"gainers": [], "losers": []}