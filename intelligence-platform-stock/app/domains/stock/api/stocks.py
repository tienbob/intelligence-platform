"""
Stock API endpoints (Section 44).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers import FinnhubProvider, ProviderError
from app.domains.stock.schemas.stock import StockPriceHistory, StockPricePoint, StockQuote
from app.domains.stock.services.company_resolution import (
    get_or_schedule_missing,
    ingestion_pending,
)

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/{ticker}", response_model=StockQuote)
async def get_stock_quote(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get the latest stock quote (Section 44)."""
    company = await get_or_schedule_missing(ticker, db)
    if company is None:
        # First sighting of this ticker: ingestion was scheduled durably and
        # runs in the worker. Answer promptly instead of running a 365-day
        # provider + scoring pipeline inside the request (audit O02), which
        # used to outlast the gateway's 30s upstream timeout and turn a
        # working ingest into a browser 502.
        raise ingestion_pending(ticker)

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
            provider = FinnhubProvider()
            try:
                quote = await provider.get_quote(ticker)
            finally:
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
    start_date: datetime = Query(default=None),
    end_date: datetime = Query(default=None),
    interval: str = Query(default="1d"),
    limit: int = Query(default=365, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Get historical stock prices (lean points: what the FE table renders)."""
    company = await get_or_schedule_missing(ticker, db)
    if company is None:
        # Scheduled for durable ingestion; do not run the provider pipeline
        # in the request (audit O02).
        raise ingestion_pending(ticker)

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
        .order_by(desc(StockPrice.timestamp))
        .limit(limit)
    )
    prices = list(reversed(price_result.scalars().all()))

    return StockPriceHistory(
        ticker=ticker.upper(),
        interval=interval,
        prices=[StockPricePoint.model_validate(p) for p in prices],
    )