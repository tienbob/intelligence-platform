"""
Market overview API endpoints (Section 47).
"""

from __future__ import annotations

import asyncio
import time
import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.macro import EconomicIndicator
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.schemas.analysis import MarketOverview
from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine

logger = get_logger(__name__)
router = APIRouter(prefix="/market", tags=["market"])

# Five-minute per-process cache; concurrent misses share one refresh.
_indices_lock = asyncio.Lock()
_indices_cache: dict[str, Any] = {}
_indices_cache_ttl: float = 300.0  # 5 minutes (was 43200.0 = 12h — audit F08)
_indices_cache_at: float = 0.0
# Last successful payload: served through provider outages so the dashboard
# degrades instead of blanking. A failed fetch is retried after
# ``_indices_failure_retry_ttl`` (short negative cache) instead of pinning an
# empty result for the full TTL (audit F08).
_indices_last_good: dict[str, Any] | None = None
_indices_failure_retry_ttl: float = 30.0
_indices_retry_after: float = 0.0

_INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "^RUT"]
_INDEX_NAMES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "DOW JONES",
    "^RUT": "RUSSELL 2000",
}


async def get_market_indices_data() -> dict[str, Any]:
    async with _indices_lock:
        return await _refresh_indices()


async def _refresh_indices() -> dict[str, Any]:
    global _indices_cache, _indices_cache_at, _indices_last_good, _indices_retry_after
    now = time.monotonic()
    if _indices_cache and now - _indices_cache_at < _indices_cache_ttl:
        return _indices_cache

    def fallback():
        return {**(_indices_last_good or {"indices": [], "fetched_at": None}), "stale": True}

    if now < _indices_retry_after:
        return fallback()

    provider = None
    try:
        provider = FMPProvider()

        async def fetch(symbol):
            try:
                # The generic provider cache lasts 24 hours. This endpoint
                # owns its five-minute freshness policy, so bypass that layer.
                quote = await asyncio.wait_for(provider.get_quote(symbol, use_cache=False), timeout=10)
                price = float(quote.get("price") or 0)
                change = float(quote.get("change") or 0)
                percent = float(quote.get("change_percent") or 0)
                if price <= 0 or not all(map(math.isfinite, (price, change, percent))):
                    return None
                if percent == 0 and change and price != change:
                    percent = change / (price - change) * 100
                return {"name": _INDEX_NAMES[symbol], "price": price,
                        "change": change, "change_percent": round(percent, 2)}
            except Exception as exc:
                logger.warning("Failed to fetch index %s: %s", symbol, exc)
                return None

        rows = await asyncio.gather(*(fetch(symbol) for symbol in _INDEX_SYMBOLS))
        indices = [row for row in rows if row is not None]
        if indices:
            result = {"indices": indices, "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "stale": False, "partial": len(indices) < len(_INDEX_SYMBOLS)}
            _indices_cache = result
            _indices_last_good = result
            _indices_cache_at = time.monotonic()
            _indices_retry_after = 0
            return result
    except Exception as exc:
        logger.warning("Index refresh failed: %s", exc)
    finally:
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                logger.warning("Could not close index provider", exc_info=True)
    _indices_retry_after = time.monotonic() + _indices_failure_retry_ttl
    return fallback()


@router.get("/overview", response_model=MarketOverview)
async def get_market_overview(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Get market overview (lean: only fields the FE renders)."""
    macro_engine = MacroAnalysisEngine(db)
    macro_snapshot = await macro_engine.get_macro_snapshot()

    # Recent major events
    event_result = await db.execute(
        select(MarketEvent)
        .order_by(desc(MarketEvent.event_date))
        .limit(10)
    )
    events = event_result.scalars().all()

    # VIX for volatility assessment
    vix_result = await db.execute(
        select(EconomicIndicator)
        .where(EconomicIndicator.indicator == "vix")
        .order_by(desc(EconomicIndicator.timestamp))
        .limit(1)
    )
    vix = vix_result.scalar_one_or_none()

    # Determine market trend from macro.
    # "unknown" regime must propagate as "unknown", never default to neutral.
    regime = macro_snapshot.get("economic_regime", "unknown")
    if regime == "expansion":
        trend = "bullish"
    elif regime in ("contraction_risk", "high_volatility"):
        trend = "bearish"
    elif regime == "unknown":
        trend = "unknown"
    else:
        trend = "neutral"

    # Explicit VIX checks — a missing VIX must yield "unknown", not "low".
    vix_value = vix.value if vix is not None else None
    if vix_value is None:
        volatility = "unknown"
    elif vix_value > 30:
        volatility = "high"
    elif vix_value > 20:
        volatility = "moderate"
    else:
        volatility = "low"

    if regime in ("contraction_risk", "high_volatility"):
        risk_level = "high"
    elif regime == "unknown":
        risk_level = "unknown"
    elif volatility == "moderate":
        risk_level = "medium"
    elif volatility == "unknown":
        risk_level = "unknown"
    else:
        risk_level = "low"

    # Lean macro: only keys the FE renders (Market/Dashboard + News VIX widget).
    lean_macro = {
        k: macro_snapshot.get(k)
        for k in (
            "fed_funds_rate",
            "treasury_10y",
            "cpi",
            "unemployment_rate",
            "vix",
            "yield_curve_slope",
        )
    }

    return MarketOverview(
        market={
            "trend": trend,
            "volatility": volatility,
            "risk_level": risk_level,
            "economic_regime": regime,
        },
        major_events=[
            {
                "id": e.id,
                "type": e.event_type,
                "date": e.event_date.isoformat(),
                "impact": e.impact,
                "description": e.description,
            }
            for e in events[:limit]
        ],
        macro_environment=lean_macro,
    )


@router.get("/indices")
async def get_market_indices():
    """Get major market indices from FMP provider (cached for five minutes)."""
    return await get_market_indices_data()


@router.get("/top-movers")
async def get_top_movers(db: AsyncSession = Depends(get_db)):
    """Get top daily movers from stock prices with real price/change/volume data."""
    # Get latest price for each company
    subq = (
        select(
            StockPrice.company_id,
            func.max(StockPrice.timestamp).label("max_ts"),
        )
        .where(StockPrice.interval == "1d")
        .group_by(StockPrice.company_id)
        .subquery()
    )

    latest = (
        select(StockPrice, Company.ticker, Company.name)
        .join(subq, (StockPrice.company_id == subq.c.company_id) & (StockPrice.timestamp == subq.c.max_ts))
        .join(Company, StockPrice.company_id == Company.id)
        .order_by(desc(func.abs(StockPrice.close - StockPrice.open) / StockPrice.open * 100))
        .limit(10)
    )

    result = await db.execute(latest)
    rows = result.all()

    movers = []
    for price, ticker, name in rows:
        change_pct = ((price.close - price.open) / price.open * 100) if price.open else 0
        movers.append({
            "ticker": ticker,
            "name": name,
            "price": price.close,
            "change_percent": change_pct,
            "volume": price.volume,
            "up": change_pct >= 0,
        })

    return {"top_movers": movers}