"""
Price API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, prices are only returned for companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.schemas.stock import StockPriceHistory, StockPricePoint
from app.shared.identity import company_is_scoped, requester_scope

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/{ticker}", response_model=StockPriceHistory)
async def get_prices(
    ticker: str,
    request: Request,
    start_date: datetime = Query(default=None),
    end_date: datetime = Query(default=None),
    interval: str = Query(default="1d"),
    db: AsyncSession = Depends(get_db),
):
    """Get historical prices for a ticker — scoped to the requesting user."""
    scope = await requester_scope(request, db)
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company or not company_is_scoped(company.id, scope):
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