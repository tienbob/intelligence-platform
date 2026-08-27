"""
API v1 router aggregation — endpoint modules.
NOTE: These are now mounted under /internal (service-key protected) by
app/api/internal/router.py. The public /api/v1 is served by the Rails gateway,
which proxies to /internal. User-JWT auth is owned by Rails, so no auth
dependency is applied here.
"""

from __future__ import annotations

from fastapi import APIRouter

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

api_router = APIRouter()

api_router.include_router(stocks.router)
api_router.include_router(companies.router)
api_router.include_router(prices.router)
api_router.include_router(financials.router)
api_router.include_router(news.router)
api_router.include_router(events.router)
api_router.include_router(market.router)
api_router.include_router(analysis.router)
api_router.include_router(investments.router)
api_router.include_router(portfolio.router)
api_router.include_router(alerts.router)
api_router.include_router(backtest.router)
