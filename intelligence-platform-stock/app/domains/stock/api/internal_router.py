"""
Internal API router — Rails→Python gateway.

Reuses the existing endpoint routers but authenticates via the internal
service key instead of user JWTs. Mounted at /internal in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import verify_internal_service_key
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