"""
Market data worker (Section 41).

Every 15 minutes: Update selected market data.
"""

from __future__ import annotations

from sqlalchemy import select, func

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.ingestion.market import MarketDataIngestion
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers.base import RateLimitError
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.config import get_stock_config


logger = get_logger(__name__)


async def update_market_data() -> None:
    """Update market data for all tracked companies."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(Company.ticker)
            .outerjoin(StockPrice, (StockPrice.company_id == Company.id) & (StockPrice.interval == "1d"))
            .group_by(Company.id, Company.ticker)
            .order_by(func.max(StockPrice.timestamp).asc().nullsfirst(), Company.id)
        )
        tickers = result.scalars().all()

        ingestion = MarketDataIngestion(
            session,
            fallback=FMPProvider() if get_stock_config().FMP_API_KEY else None,
        )

        try:
            for ticker in tickers:
                try:
                    await ingestion.ingest_recent_prices(
                        ticker,
                        days=5,
                    )
                except RateLimitError:
                    await session.rollback()
                    logger.warning("Market quota exhausted; remaining tickers deferred to next run")
                    break
                except Exception as exc:
                    await session.rollback()
                    logger.error(
                        "Failed to update market data for %s: %s",
                        ticker,
                        exc,
                        exc_info=True,
                    )

        finally:
            await ingestion.close()

        logger.info(
            "Market data update complete for %d companies",
            len(tickers),
        )