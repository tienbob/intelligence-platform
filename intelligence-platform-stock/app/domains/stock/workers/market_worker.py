"""
Market data worker (Section 41).

Every 15 minutes: Update selected market data.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.ingestion.market import MarketDataIngestion
from app.domains.stock.models.company import Company
from app.domains.stock.providers.fmp import FMPProvider


logger = get_logger(__name__)


async def update_market_data() -> None:
    """Update market data for all tracked companies."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(Company.ticker).limit(100)
        )
        tickers = result.scalars().all()

        # Use FMP directly — Massive is currently rate-limited.
        ingestion = MarketDataIngestion(
            session,
            provider=FMPProvider(),
        )

        for ticker in tickers:
            try:
                await ingestion.ingest_recent_prices(
                    ticker,
                    days=5,
                )
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "Failed to update market data for %s: %s",
                    ticker,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Market data update complete for %d companies",
            len(tickers),
        )