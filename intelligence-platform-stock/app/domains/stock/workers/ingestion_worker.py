"""
Raw/canonical ingestion worker (Section 16).

Daily: ingest fundamentals and macro indicators for tracked companies.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.ingestion.fundamentals import FundamentalsIngestion
from app.domains.stock.ingestion.macro import MacroIngestion
from app.domains.stock.models.company import Company

logger = get_logger(__name__)


async def ingest_fundamentals() -> None:
    """Ingest fundamentals for tracked companies."""

    async with async_session_factory() as session:
        # Select scalar values instead of ORM objects.
        #
        # FundamentalsIngestion commits internally, which can expire
        # ORM instances when expire_on_commit=True. Keeping only the
        # ticker string avoids implicit async attribute reloads and
        # MissingGreenlet errors.
        result = await session.execute(
            select(Company.id, Company.ticker).limit(50)
        )
        companies = result.all()

        ingestion = FundamentalsIngestion(session)

        for _company_id, ticker in companies:
            try:
                await ingestion.ingest_fmp_statements(ticker)
                await ingestion.ingest_company_profile(ticker)

            except Exception as exc:
                logger.error(
                    "Failed to ingest fundamentals for %s: %s",
                    ticker,
                    exc,
                )

        logger.info(
            "Fundamentals ingestion complete for %d companies",
            len(companies),
        )


async def ingest_macro_indicators() -> None:
    """Ingest macroeconomic indicators from the configured provider."""

    async with async_session_factory() as session:
        ingestion = MacroIngestion(session)

        try:
            results = await ingestion.ingest_all_indicators()

            logger.info(
                "Macro indicator ingestion complete: %s",
                results,
            )

        except Exception as exc:
            logger.error(
                "Failed to ingest macro indicators: %s",
                exc,
            )