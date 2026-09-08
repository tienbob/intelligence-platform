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


async def ingest_sec_filings() -> None:
    """Ingest SEC XBRL company facts and build filing chunks for RAG.

    Companies without a SEC CIK, or instruments whose CIK is not
    supported by the SEC Company Facts endpoint, are skipped.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Company.id,
                Company.ticker,
                Company.cik,
            ).limit(50)
        )
        companies = result.all()

        ingestion = FundamentalsIngestion(session)

        for company_id, ticker, company_cik in companies:
            ticker = ticker.upper().strip() if ticker else ""

            if not company_cik:
                logger.info(
                    "Skipping SEC ingestion for %s: no SEC CIK",
                    ticker,
                )
                continue

            try:
                cik = str(company_cik).strip().zfill(10)

                await ingestion.ingest_sec_facts(
                    cik=cik,
                    ticker=ticker,
                    company_id=company_id,
                )

            except Exception as exc:
                # SEC Company Facts returns 404 for instruments that have
                # a CIK record but no Company Facts dataset, such as ETFs.
                if "HTTP 404" in str(exc):
                    logger.info(
                        "Skipping SEC ingestion for %s: "
                        "SEC Company Facts unavailable for CIK %s",
                        ticker,
                        cik,
                    )
                    continue

                logger.error(
                    "Failed to ingest SEC filings for %s: %s",
                    ticker,
                    exc,
                )

        logger.info(
            "SEC filing ingestion complete for %d companies",
            len(companies),
        )


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