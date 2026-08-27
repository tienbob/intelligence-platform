"""
Data ingestion script.

Usage:
    python -m scripts.ingest prices AAPL
    python -m scripts.ingest fundamentals AAPL
    python -m scripts.ingest news AAPL
    python -m scripts.ingest macro
    python -m scripts.ingest profile AAPL
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from app.core.database import async_session_factory
from app.core.logging import setup_logging
from app.domains.stock.ingestion.fundamentals import FundamentalsIngestion
from app.domains.stock.ingestion.macro import MacroIngestion
from app.domains.stock.ingestion.market import MarketDataIngestion
from app.domains.stock.ingestion.news import NewsIngestion

setup_logging()


async def ingest_prices(ticker: str) -> None:
    async with async_session_factory() as session:
        ingestion = MarketDataIngestion(session)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=365)
        count = await ingestion.ingest_historical_prices(ticker, start, end, "1d")
        print(f"Ingested {count} price points for {ticker}")


async def ingest_fundamentals(ticker: str) -> None:
    async with async_session_factory() as session:
        ingestion = FundamentalsIngestion(session)
        count = await ingestion.ingest_fmp_statements(ticker)
        print(f"Ingested {count} financial statements for {ticker}")
        await ingestion.ingest_company_profile(ticker)
        print(f"Updated company profile for {ticker}")


async def ingest_news(ticker: str) -> None:
    async with async_session_factory() as session:
        ingestion = NewsIngestion(session)
        count = await ingestion.ingest_company_news(ticker, limit=50)
        print(f"Ingested {count} news items for {ticker}")


async def ingest_macro() -> None:
    async with async_session_factory() as session:
        ingestion = MacroIngestion(session)
        results = await ingestion.ingest_all_indicators()
        for indicator, result in results.items():
            if isinstance(result, dict):
                inserted = result.get("inserted", 0)
                skipped = result.get("skipped", 0)
                error = result.get("error")
                if error:
                    print(f"  {indicator}: ERROR - {error}")
                else:
                    print(f"  {indicator}: {inserted} data points (skipped {skipped})")
            else:
                print(f"  {indicator}: {result} data points")


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]
    ticker = sys.argv[2].upper() if len(sys.argv) > 2 else None

    if command == "prices" and ticker:
        await ingest_prices(ticker)
    elif command == "fundamentals" and ticker:
        await ingest_fundamentals(ticker)
    elif command == "news" and ticker:
        await ingest_news(ticker)
    elif command == "macro":
        await ingest_macro()
    else:
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
