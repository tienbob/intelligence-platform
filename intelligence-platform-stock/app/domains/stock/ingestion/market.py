"""
Market data ingestion (Section 16).

Pipeline:

    External Provider → Provider Adapter → Auth → Rate Limit → Request
    → Retry → Raw Payload → Store Raw → Validate → Normalize → Store Canonical
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.models.raw import RawMarketData
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers import MassiveProvider, ProviderError
from app.domains.stock.providers.base import RateLimitError
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.normalization.companies import EntityResolver
from app.domains.stock.validation.freshness import (
    check_freshness,
    classify_freshness,
)
from app.domains.stock.validation.schema import validate_stock_price
from app.domains.stock.validation.duplicates import is_duplicate_stock_price


logger = get_logger(__name__)


class MarketDataIngestion:
    """
    Ingest market data from providers.

    The primary and fallback providers are explicitly configured.

    Important:
    - The primary provider is never mutated.
    - Fallback is optional.
    - A fallback is only attempted when it is a different provider.
    - The provider that actually supplied the data is tracked per request.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: MassiveProvider | FMPProvider | None = None,
        fallback: MassiveProvider | FMPProvider | None = None,
    ):
        self.session = session
        self._primary = provider or MassiveProvider()
        self._fallback = fallback
        self._entity_resolver = EntityResolver(session)

    @property
    def provider(self):
        """
        Return the configured primary provider.

        This property is retained for compatibility with existing callers.
        For source attribution inside ingestion methods, use the actual
        provider selected for the current request instead.
        """
        return self._primary

    async def _store_raw(
        self,
        endpoint: str,
        ticker: str | None,
        payload: dict[str, Any],
        provider_name: str | None = None,
    ) -> RawMarketData:
        """Store the raw provider response (Section 8)."""

        raw = RawMarketData(
            provider=provider_name or self.provider.provider_name,
            endpoint=endpoint,
            ticker=ticker,
            retrieved_at=datetime.now(timezone.utc),
            payload=payload,
        )

        self.session.add(raw)
        await self.session.flush()

        return raw

    async def _get_or_create_company(self, ticker: str) -> Company:
        """Resolve ticker to a company record using entity resolution service."""
        return await self._entity_resolver.resolve_or_create(ticker=ticker)

    def _can_fallback(self) -> bool:
        """
        Return whether the configured fallback is actually a different provider.

        This prevents accidental FMP → FMP or Massive → Massive duplicate
        requests when the primary provider is already the fallback.
        """

        if self._fallback is None:
            return False

        return (
            self._fallback.provider_name
            != self._primary.provider_name
        )

    async def _get_historical_prices_with_fallback(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
    ) -> tuple[list[dict[str, Any]], Any]:
        """
        Fetch historical prices using primary/fallback provider policy.

        Returns:
            (prices, actual_provider)

        The primary provider is never replaced or mutated.

        RateLimitError is treated specially:
        - If there is a genuinely different fallback provider, use it.
        - Otherwise propagate the rate-limit error immediately.
        """

        try:
            prices = await self._primary.get_historical_prices(
                ticker,
                start_date,
                end_date,
                interval,
            )

            if prices:
                return prices, self._primary

            logger.info(
                "Primary provider %s returned no prices for %s",
                self._primary.provider_name,
                ticker,
            )

        except RateLimitError:
            # Never retry a rate-limited provider through another instance
            # of the exact same provider.
            if not self._can_fallback():
                raise

            logger.warning(
                "Primary provider %s is rate-limited for %s; "
                "using fallback provider %s",
                self._primary.provider_name,
                ticker,
                self._fallback.provider_name,
            )

        except ProviderError as exc:
            if not self._can_fallback():
                raise

            logger.warning(
                "Primary provider %s failed for %s: %s; "
                "using fallback provider %s",
                self._primary.provider_name,
                ticker,
                exc,
                self._fallback.provider_name,
            )

        if not self._can_fallback():
            return [], self._primary

        prices = await self._fallback.get_historical_prices(
            ticker,
            start_date,
            end_date,
            interval,
        )

        return prices, self._fallback

    async def ingest_quote(self, ticker: str) -> dict[str, Any]:
        """Fetch and store a stock quote."""

        try:
            raw_data = await self.provider.get_quote(ticker)

            await self._store_raw(
                f"/quote/{ticker}",
                ticker,
                raw_data,
                provider_name=self.provider.provider_name,
            )

            await self.session.commit()

            logger.info("Ingested quote for %s", ticker)

            return raw_data

        except ProviderError as exc:
            await self.session.rollback()

            logger.error(
                "Failed to ingest quote for %s: %s",
                ticker,
                exc,
            )

            raise

    async def ingest_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> int:
        """
        Fetch and store historical OHLCV prices.

        Returns the number of price points stored.
        """

        try:
            prices, source_provider = (
                await self._get_historical_prices_with_fallback(
                    ticker,
                    start_date,
                    end_date,
                    interval,
                )
            )

            source_name = source_provider.provider_name

            # Store raw payload.
            #
            # Providers may return datetime objects, which are not directly
            # JSON serializable for PostgreSQL JSONB.
            raw_payload = {
                "results": [
                    {
                        **p,
                        "timestamp": (
                            p["timestamp"].isoformat()
                            if isinstance(
                                p.get("timestamp"),
                                datetime,
                            )
                            else p.get("timestamp")
                        ),
                    }
                    for p in prices
                ]
            }

            await self._store_raw(
                f"/aggs/ticker/{ticker}",
                ticker,
                raw_payload,
                provider_name=source_name,
            )

            # Freshness check.
            #
            # Validate the age of the provider's latest price point,
            # not the timestamp at which we stored the response.
            if prices:
                latest_price_ts = prices[-1].get("timestamp")

                if isinstance(latest_price_ts, (int, float)):
                    latest_price_dt = datetime.fromtimestamp(
                        (
                            latest_price_ts / 1000
                            if latest_price_ts > 1e12
                            else latest_price_ts
                        ),
                        tz=timezone.utc,
                    )

                elif isinstance(latest_price_ts, str):
                    latest_price_dt = datetime.fromisoformat(
                        latest_price_ts.replace("Z", "+00:00")
                    )

                elif isinstance(latest_price_ts, datetime):
                    latest_price_dt = latest_price_ts

                    if latest_price_dt.tzinfo is None:
                        latest_price_dt = latest_price_dt.replace(
                            tzinfo=timezone.utc
                        )

                else:
                    latest_price_dt = None

                if latest_price_dt is not None:
                    data_age_seconds = (
                        datetime.now(timezone.utc) - latest_price_dt
                    ).total_seconds()

                    freshness = classify_freshness(data_age_seconds)
                    is_fresh = check_freshness(latest_price_dt)

                    if not is_fresh:
                        logger.warning(
                            "Data freshness check failed for %s: "
                            "age=%.0fs, freshness=%s",
                            ticker,
                            data_age_seconds,
                            freshness.value,
                        )

            # Normalize into canonical stock_prices.
            company = await self._get_or_create_company(ticker)

            count = 0

            for price in prices:
                ts = price.get("timestamp")

                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(
                        ts / 1000 if ts > 1e12 else ts,
                        tz=timezone.utc,
                    )

                elif isinstance(ts, str):
                    ts = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    )

                elif isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                # Daily bars key on calendar day rather than time-of-day.
                if interval == "1d" and ts is not None:
                    ts = ts.replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )

                # Providers may return fractional adjusted volume.
                volume = price.get("volume", 0)

                if volume is not None:
                    volume = int(round(volume))

                validation_data = {
                    "ticker": ticker,
                    "timestamp": ts,
                    "open": price.get("open", 0),
                    "high": price.get("high", 0),
                    "low": price.get("low", 0),
                    "close": price.get("close", 0),
                    "adjusted_close": price.get("adjusted_close"),
                    "volume": volume,
                    "source": source_name,
                }

                validation_result = validate_stock_price(
                    validation_data
                )

                if not validation_result:
                    logger.warning(
                        "Skipping invalid price data for %s: %s",
                        ticker,
                        validation_result.errors,
                    )
                    continue

                insert_stmt = insert(StockPrice).values(
                    company_id=company.id,
                    timestamp=ts,
                    interval=interval,
                    open=price.get("open", 0),
                    high=price.get("high", 0),
                    low=price.get("low", 0),
                    close=price.get("close", 0),
                    adjusted_close=price.get("adjusted_close"),
                    volume=volume,
                    source=source_name,
                ).on_conflict_do_nothing(
                    index_elements=[
                        "company_id",
                        "interval",
                        "timestamp",
                    ]
                )

                result = await self.session.execute(insert_stmt)

                if result.rowcount == 0:
                    logger.debug(
                        "Skipping duplicate price for %s at %s",
                        ticker,
                        ts,
                    )
                    continue

                count += 1

            await self.session.commit()

            logger.info(
                "Ingested %d price points for %s from %s",
                count,
                ticker,
                source_name,
            )

            return count

        except ProviderError as exc:
            await self.session.rollback()

            logger.error(
                "Failed to ingest prices for %s: %s",
                ticker,
                exc,
            )

            raise

        except Exception as exc:
            # Ensure DB consistency on unexpected errors.
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting prices for %s: %s",
                ticker,
                exc,
            )

            raise

    async def ingest_market_movers(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch and store market movers."""

        try:
            movers = await self.provider.get_market_movers()

            await self._store_raw(
                "/snapshot/movers",
                None,
                movers,
                provider_name=self.provider.provider_name,
            )

            await self.session.commit()

            logger.info(
                "Ingested market movers: %d gainers, %d losers",
                len(movers.get("gainers", [])),
                len(movers.get("losers", [])),
            )

            return movers

        except ProviderError as exc:
            await self.session.rollback()

            logger.error(
                "Failed to ingest market movers: %s",
                exc,
            )

            raise

    async def ingest_recent_prices(
        self,
        ticker: str,
        days: int = 365,
    ) -> int:
        """Convenience method to ingest recent daily prices."""

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        return await self.ingest_historical_prices(
            ticker,
            start_date,
            end_date,
            "1d",
        )