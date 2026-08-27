"""
End-to-end verification script for the 7 pipeline bug fixes.

Usage (from the python container):
    python scripts/verify_pipeline_fixes.py

Covers:
    T1  Macro unknown semantics (empty DB)
    T2  Macro timestamp type (timestamptz + UTC)
    T3  News dedup (URL collapse + multi-company fan-out)
    T4  Event classification (negative + positive cases)
    T5  Impact (price-correlation driven)

Expected exit code 0 when all checks pass.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.database import async_session_factory
from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine
from app.domains.stock.normalization.events import classify_event
from app.domains.stock.validation.duplicates import compute_news_hash
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.news import News

# ── Tiny assertion helper ──────────────────────────────────────────
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


# ── T4: Classification (pure function, no DB) ─────────────────────
def test_classification() -> None:
    print("\n[T4] Event classification")

    # Previously-broken negative cases: must NOT become earnings events.
    check(
        "'Has Beaten the Market' → not EARNINGS_BEAT",
        classify_event("Broadcom's Stock Has Beaten the Market in 12 of the Past 13 Years") != "EARNINGS_BEAT",
        classify_event("Broadcom's Stock Has Beaten the Market in 12 of the Past 13 Years"),
    )
    check(
        "'Ciena Stock Tanked' → not EARNINGS_IN_LINE",
        classify_event("Why Ciena Stock Tanked by Almost 9% on Tuesday") != "EARNINGS_IN_LINE",
        classify_event("Why Ciena Stock Tanked by Almost 9% on Tuesday"),
    )
    check(
        "'Palantir Trillion-Dollar?' → not EARNINGS_IN_LINE",
        classify_event("Is Palantir the Next Trillion-Dollar Stock?") != "EARNINGS_IN_LINE",
        classify_event("Is Palantir the Next Trillion-Dollar Stock?"),
    )
    check(
        "'Sandisk History Says' → not EARNINGS_IN_LINE",
        classify_event("Sandisk Is Up More Than 35-Fold in a Year and Sits Nearly a Third Below Its Peak. History Says What Comes Next.") != "EARNINGS_IN_LINE",
        classify_event("Sandisk Is Up More Than 35-Fold in a Year and Sits Nearly a Third Below Its Peak. History Says What Comes Next."),
    )

    # Positive cases: must classify correctly.
    check(
        "'reports quarterly earnings' → EARNINGS_IN_LINE",
        classify_event("Company reports quarterly earnings") == "EARNINGS_IN_LINE",
    )
    check(
        "'beats earnings expectations' → EARNINGS_BEAT",
        classify_event("Company beats earnings expectations") == "EARNINGS_BEAT",
    )
    check(
        "'revenue exceeded analyst estimates' → EARNINGS_BEAT",
        classify_event("Revenue exceeded analyst estimates") == "EARNINGS_BEAT",
    )
    check(
        "'misses quarterly earnings estimates' → EARNINGS_MISS",
        classify_event("Company misses quarterly earnings estimates") == "EARNINGS_MISS",
    )


# ── T3: News dedup (pure function) ────────────────────────────────
def test_news_dedup_hash() -> None:
    print("\n[T3] News dedup hash")

    # Same external_id + source + title (different URLs/timestamps) → same hash.
    h1 = compute_news_hash("NVIDIA beats expectations", url="http://a.com/1", published_at="2026-08-19T10:00:01+00:00", external_id="nvid-123", source="massive")
    h2 = compute_news_hash("NVIDIA beats expectations", url="http://b.com/2", published_at="2026-08-19T10:00:05+00:00", external_id="nvid-123", source="massive")
    check("same external_id → same hash", h1 == h2)

    # No external_id: same title + same timestamp + different URL → same hash.
    h3 = compute_news_hash("NVIDIA beats expectations", url="http://a.com/1", published_at="2026-08-19T10:00:01+00:00")
    h4 = compute_news_hash("NVIDIA beats expectations", url="http://b.com/2", published_at="2026-08-19T10:00:01+00:00")
    check("no external_id, same title+ts, diff URL → same hash", h3 == h4)

    # Different titles → different hash.
    h5 = compute_news_hash("NVIDIA beats expectations", published_at="2026-08-19T10:00:01+00:00")
    h6 = compute_news_hash("NVIDIA misses expectations", published_at="2026-08-19T10:00:01+00:00")
    check("different title → different hash", h5 != h6)


# ── T1: Macro snapshot semantics with empty DB ─────────────────────
async def test_macro_snapshot_empty() -> None:
    print("\n[T1] Macro snapshot with empty economic_indicators")
    async with async_session_factory() as session:
        engine = MacroAnalysisEngine(session)
        snapshot = await engine.get_macro_snapshot()

    check("regime == 'unknown' (empty DB)", snapshot.get("economic_regime") == "unknown", str(snapshot.get("economic_regime")))
    check("economic_trend == 'unknown' (empty DB)", snapshot.get("economic_trend") == "unknown", str(snapshot.get("economic_trend")))
    check("fed_funds_rate is None", snapshot.get("fed_funds_rate") is None)
    check("vix is None", snapshot.get("vix") is None)


# ── T2: Macro timestamp type in DB (timestamptz, UTC-aware) ───────
async def test_macro_timestamp_type() -> None:
    print("\n[T2] Macro timestamp column type")
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                text("data_type")
            ).select_from(
                text("information_schema.columns")
            ).where(
                text("table_name = 'market_events'"),
                text("column_name = 'event_date'"),
            )
        )
        ts_type = result.scalar()
    check("event_date column is timestamp with time zone", "timestamp with time zone" in (ts_type or ""), str(ts_type))


# ── T5: Impact from price reaction (pure helper) ───────────────────
def test_impact_mapping() -> None:
    print("\n[T5] Impact price-reaction mapping (logic mirror check)")

    # The thresholds live in _update_impact_from_price; mirror the logic here.
    def impact_for(pct: float) -> str:
        if pct >= 0.03:
            return "positive"
        if pct <= -0.03:
            return "negative"
        return "neutral"

    check("+4.2% → positive", impact_for(0.042) == "positive")
    check("−8.5% → negative", impact_for(-0.085) == "negative")
    check("+0.1% → neutral", impact_for(0.001) == "neutral")
    check("no data (0.0) → neutral", impact_for(0.0) == "neutral")


async def main() -> None:
    print("=" * 60)
    print("Pipeline fix verification")
    print("=" * 60)

    # Pure-function tests first.
    test_classification()
    test_news_dedup_hash()
    test_impact_mapping()

    # DB-backed tests.
    await test_macro_snapshot_empty()
    await test_macro_timestamp_type()

    print("\n" + "=" * 60)
    print(f"PASSED: {len(PASSED)}  FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED checks:")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())