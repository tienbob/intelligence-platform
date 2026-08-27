"""
Market overview API endpoints (Section 47).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.domains.stock.models.analysis import AnomalyScore
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.macro import EconomicIndicator
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.schemas.analysis import MarketOverview
from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine

logger = get_logger(__name__)
router = APIRouter(prefix="/market", tags=["market"])

# Module-level cache for market indices to prevent spamming FMP on every
# frontend poll. The provider layer also caches individual GET responses
# in Redis (24h TTL), but this cache short-circuits the entire endpoint
# so we don't even create a provider instance on repeated polls.
_indices_cache: dict[str, Any] = {}
_indices_cache_ttl: float = 43200.0  # 5 minutes
_indices_cache_at: float = 0.0

_INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "^RUT"]
_INDEX_NAMES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "DOW JONES",
    "^RUT": "RUSSELL 2000",
}


async def get_market_indices_data() -> dict[str, Any]:
    """Fetch market indices with module-level caching (shared by endpoints)."""
    global _indices_cache, _indices_cache_at

    now = time.monotonic()
    if _indices_cache and (now - _indices_cache_at) < _indices_cache_ttl:
        return _indices_cache

    try:
        provider = FMPProvider()
        indices = {}
        for symbol in _INDEX_SYMBOLS:
            try:
                # Provider calls are cached in Redis (24h TTL), so only the first
                # call hits FMP; subsequent calls return instantly from cache.
                quote = await asyncio.wait_for(provider.get_quote(symbol), timeout=10.0)
                price = quote.get("price", 0)
                change = quote.get("change", 0)
                # FMP may not return change_percent for indices; compute it
                change_pct = quote.get("change_percent", 0)
                if change_pct == 0 and price and change:
                    prev_close = price - change
                    if prev_close:
                        change_pct = (change / prev_close) * 100
                indices[symbol] = {
                    "name": _INDEX_NAMES.get(symbol, symbol),
                    "price": price,
                    "change": change,
                    "change_percent": round(change_pct, 2),
                }
            except asyncio.TimeoutError:
                logger.warning("Timed out fetching index %s", symbol)
            except Exception as exc:
                logger.warning("Failed to fetch index %s: %s", symbol, exc)
        await provider.close()
        result = {"indices": list(indices.values())}
        _indices_cache = result
        _indices_cache_at = now
        return result
    except Exception as exc:
        logger.error("Failed to fetch indices: %s", exc)
        return {"indices": []}


@router.get("/overview", response_model=MarketOverview)
async def get_market_overview(db: AsyncSession = Depends(get_db)):
    """Get market overview (Section 47)."""
    macro_engine = MacroAnalysisEngine(db)
    macro_snapshot = await macro_engine.get_macro_snapshot()

    # Market indices (from the shared cached helper)
    indices_data = await get_market_indices_data()
    indices = indices_data.get("indices", [])

    # Recent anomalies
    anomaly_result = await db.execute(
        select(AnomalyScore)
        .where(AnomalyScore.triggered == True)  # noqa: E712
        .order_by(desc(AnomalyScore.timestamp))
        .limit(10)
    )
    anomalies = anomaly_result.scalars().all()

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

    # Distinguish "no movers" from "no data" / "provider failure".
    if anomalies:
        movers_status = "ok"
        movers_reason = None
    else:
        movers_status = "no_data"
        movers_reason = "No companies exceeded the anomaly movement threshold"

    return MarketOverview(
        market={
            "trend": trend,
            "volatility": volatility,
            "risk_level": risk_level,
            "economic_regime": regime,
        },
        indices={"indices": indices},
        top_movers=[
            {
                "company_id": a.company_id,
                "score": a.overall_score,
                "triggered": a.triggered,
            }
            for a in anomalies
        ],
        top_movers_status=movers_status,
        top_movers_reason=movers_reason,
        major_events=[
            {
                "id": e.id,
                "type": e.event_type,
                "date": e.event_date.isoformat(),
                "impact": e.impact,
                "description": e.description,
            }
            for e in events
        ],
        macro_environment=macro_snapshot,
    )


@router.get("/indices")
async def get_market_indices():
    """Get major market indices from FMP provider (cached 5 min module-level + 24h Redis)."""
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
            "change": change_pct,
            "change_percent": change_pct,
            "volume": price.volume,
            "up": change_pct >= 0,
        })

    return {"top_movers": movers}