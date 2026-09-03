"""
Internal API router — Rails→Python gateway.

Reuses the existing endpoint routers but authenticates via the internal
service key instead of user JWTs. Mounted at /internal in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_internal_service_key
from app.domains.stock.models.company import Company
from app.domains.stock.api import (
    alerts,
    analysis,
    backtest,
    companies,
    events,
    financials,
    investments,
    market,
    news,
    portfolio,
    prices,
    stocks,
)

internal_router = APIRouter(
    dependencies=[Depends(verify_internal_service_key)],
)

internal_router.include_router(stocks.router)
internal_router.include_router(companies.router)
internal_router.include_router(prices.router)
internal_router.include_router(financials.router)
internal_router.include_router(news.router)
internal_router.include_router(events.router)
internal_router.include_router(market.router)
internal_router.include_router(analysis.router)
internal_router.include_router(investments.router)
internal_router.include_router(portfolio.router)
internal_router.include_router(alerts.router)
internal_router.include_router(backtest.router)


@internal_router.post("/companies/{ticker}/ensure")
async def internal_ensure_company(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """Idempotently ensure a ticker is tracked — summon (ingest) if missing.

    Called by the Rails gateway before proxying ticker-scoped reads for
    logged-in users. Python owns ingestion (it performs the summon here);
    Rails then writes the ``user_companies`` grant, which it owns per
    docs/TABLE_OWNERSHIP.md.
    """
    from app.domains.stock.api.stocks import _auto_ingest_ticker

    symbol = ticker.upper()
    existing = (
        await db.execute(select(Company).where(Company.ticker == symbol))
    ).scalar_one_or_none()
    if existing:
        return {"ticker": symbol, "company_id": existing.id, "created": False}

    company = await _auto_ingest_ticker(symbol, db)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {symbol} not found")
    return {"ticker": symbol, "company_id": company.id, "created": True}


@internal_router.get("/health/live")
async def internal_health_live():
    return {"status": "ok"}


@internal_router.get("/health/ready")
async def internal_health_ready():
    from app.core.database import engine
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "degraded"
    return {"status": "ok" if db_status == "ok" else "degraded", "database": db_status}


@internal_router.get("/health")
async def internal_health():
    return {"status": "ok"}


@internal_router.get("/metrics")
async def internal_metrics():
    from app.core.observability import get_metrics_snapshot
    return get_metrics_snapshot()