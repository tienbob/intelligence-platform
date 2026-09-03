"""
Stock API endpoints (Section 44).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers import MassiveProvider, ProviderError
from app.domains.stock.schemas.stock import StockPriceHistory, StockPricePoint, StockQuote
from app.core.database import get_db
from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers import MassiveProvider, ProviderError
from app.domains.stock.schemas.stock import StockPriceHistory, StockPricePoint, StockQuote
from app.shared.identity import company_is_scoped, requester_scope

logger = get_logger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])


async def _auto_ingest_ticker(ticker: str, db: AsyncSession) -> Company | None:
    """
    Automatically pull data for a ticker that isn't tracked yet.

    When a user searches for a ticker that doesn't exist in the DB, this
    ingests historical prices, news, and fundamentals so the platform
    self-populates on demand instead of requiring manual ingestion.

    Only step 1 is required (it creates and commits the company record and
    price history). Every later step is best-effort — and a failure there
    MUST roll the session back: swallowing the exception alone leaves the
    transaction aborted (InFailedSQLTransactionError), which poisoned the
    final company lookup and made callers report 404 for companies that
    had actually been ingested successfully.
    """
    from datetime import datetime, timedelta, timezone

    from app.domains.stock.ingestion.fundamentals import FundamentalsIngestion
    from app.domains.stock.ingestion.market import MarketDataIngestion
    from app.domains.stock.ingestion.news import NewsIngestion

    upper = ticker.upper()

    async def _best_effort(label: str, run) -> None:
        """Run an optional ingestion step without poisoning the session.

        On failure: roll back so the aborted-transaction state is cleared
        and later steps (and the final lookup) run on a clean session.
        On success: commit so a later failure cannot undo this step's work.
        """
        try:
            await run()
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(
                "Auto-ingest step '%s' failed for %s", label, ticker, exc_info=True
            )

    try:
        # 1. Ingest historical prices (creates the company record)
        market = MarketDataIngestion(db)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=365)
        await market.ingest_historical_prices(ticker, start, end, "1d")

        # 2. Ingest company profile + financial statements
        fundamentals = FundamentalsIngestion(db)
        await _best_effort("fundamentals", lambda: fundamentals.ingest_company_profile(ticker))
        await _best_effort("statements", lambda: fundamentals.ingest_fmp_statements(ticker))

        # 3. Ingest recent news
        news = NewsIngestion(db)
        await _best_effort("news", lambda: news.ingest_company_news(ticker, limit=50))

        # 3b. Detect market events from the ingested news immediately,
        # so the Market Overview "Major Events" panel has data right away
        # instead of waiting for the hourly scheduler. Use a 7-day window
        # because auto-ingested news can span several days.
        from app.domains.stock.scoring.event_detection import EventIntelligenceEngine

        async def _detect_events() -> None:
            company = (await db.execute(
                select(Company).where(Company.ticker == upper)
            )).scalar_one_or_none()
            if company:
                await EventIntelligenceEngine(db).detect_events_from_news(company.id, hours=168)

        await _best_effort("event detection", _detect_events)

        # 4. Compute derived data (technical indicators + financial metrics)
        from app.domains.stock.scoring.fundamental_analysis import FundamentalAnalysisEngine
        from app.domains.stock.scoring.technical_analysis import TechnicalAnalysisEngine

        async def _derive() -> None:
            company = (await db.execute(
                select(Company).where(Company.ticker == upper)
            )).scalar_one_or_none()
            if company:
                await TechnicalAnalysisEngine(db).calculate_indicators(company.id)
                await FundamentalAnalysisEngine(db).calculate_and_store(company.id)

        await _best_effort("derived data", _derive)

        # Final lookup — the session is clean here even if a best-effort
        # step failed above, so the caller sees the ingested company.
        result = await db.execute(
            select(Company).where(Company.ticker == upper)
        )
        return result.scalar_one_or_none()
    except Exception:
        # Step 1 itself failed (or the session is otherwise unusable).
        # Roll back so the shared session is not left aborted, then report
        # the company as absent — the caller turns this into a 404.
        await db.rollback()
        logger.exception("Auto-ingest failed for %s", ticker)
        # Concurrency: a parallel summon may have created the company after
        # our pre-check — its INSERT wins the companies.ticker unique-index
        # race and ours fails with UniqueViolationError. Adopt that row
        # instead of reporting a false 404.
        try:
            result = await db.execute(
                select(Company).where(Company.ticker == upper)
            )
            concurrent = result.scalar_one_or_none()
            if concurrent:
                logger.info(
                    "Auto-ingest for %s lost a create race; adopting existing company",
                    ticker,
                )
                return concurrent
        except Exception:
            await db.rollback()
        return None


@router.get("/{ticker}", response_model=StockQuote)
async def get_stock_quote(
    ticker: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get the latest stock quote (Section 44) — scoped per requesting user."""
    scope = await requester_scope(request, db)

    # Try DB first for latest price
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        if scope is not None:
            # Scoped users cannot summon companies they were not granted.
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        # Auto-ingest the ticker so search self-populates the platform
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        # Re-query prices after ingestion
        result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    if not company_is_scoped(company.id, scope):
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    # Get latest price from DB
    price_result = await db.execute(
        select(StockPrice)
        .where(StockPrice.company_id == company.id)
        .where(StockPrice.interval == "1d")
        .order_by(desc(StockPrice.timestamp))
        .limit(2)
    )
    prices = price_result.scalars().all()
    if not prices:
        # Fallback to provider
        try:
            provider = MassiveProvider()
            quote = await provider.get_quote(ticker)
            await provider.close()
            return StockQuote(
                ticker=ticker.upper(),
                name=company.name,
                price=quote.get("price", 0),
                change=quote.get("change", 0),
                change_percent=quote.get("change_percent", 0),
                volume=quote.get("volume", 0),
            )
        except ProviderError:
            raise HTTPException(status_code=503, detail="Unable to fetch stock quote")

    latest = prices[0]
    prev = prices[1] if len(prices) > 1 else None
    change = latest.close - prev.close if prev else 0
    change_pct = (change / prev.close * 100) if prev and prev.close else 0

    return StockQuote(
        ticker=ticker.upper(),
        name=company.name,
        price=latest.close,
        change=change,
        change_percent=change_pct,
        volume=latest.volume,
        timestamp=latest.timestamp,
    )


@router.get("/{ticker}/prices", response_model=StockPriceHistory)
async def get_stock_prices(
    ticker: str,
    request: Request,
    start_date: datetime = Query(default=None),
    end_date: datetime = Query(default=None),
    interval: str = Query(default="1d"),
    db: AsyncSession = Depends(get_db),
):
    """Get historical stock prices (Section 45) — scoped per requesting user."""
    scope = await requester_scope(request, db)
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        if scope is not None:
            # Scoped users cannot summon companies they were not granted.
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        # Auto-ingest the ticker so direct navigation self-populates
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    if not company_is_scoped(company.id, scope):
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    if not end_date:
        end_date = datetime.now(timezone.utc)
    if not start_date:
        start_date = end_date - timedelta(days=365)

    price_result = await db.execute(
        select(StockPrice)
        .where(StockPrice.company_id == company.id)
        .where(StockPrice.interval == interval)
        .where(StockPrice.timestamp >= start_date)
        .where(StockPrice.timestamp <= end_date)
        .order_by(StockPrice.timestamp)
    )
    prices = price_result.scalars().all()

    return StockPriceHistory(
        ticker=ticker.upper(),
        interval=interval,
        prices=[StockPricePoint.model_validate(p) for p in prices],
    )