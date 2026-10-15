"""One shared ticker-resolution path for reads that may need first-time data.

Audit O02: an untracked ticker used to run a 365-day price ingest plus
fundamentals, news, event detection and derived scoring *inside* the GET
handler. The gateway aborts upstream at 30s (``operation_timeout``), so a slow
provider produced a 502 in the browser while the work kept running, and every
concurrent search paid for the same provider calls again.

Resolution now has two halves:
  * ``get_or_schedule_missing`` - request path. Reads the database; when the
    ticker is absent it reserves one durable ingestion job and returns
    ``None`` promptly. No provider call happens here.
  * ``ingest_missing_ticker`` - worker path. Runs the provider and scoring work
    on a session owned by the queue worker, so an abrupt API exit leaves a
    durable row that is resumed rather than lost.

Reservation is coalesced per ticker through the existing ``work_jobs``
``uq_work_jobs_scope_key`` constraint: N concurrent requests for one unknown
ticker converge on one job, therefore on one provider pipeline.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import WorkJob
from app.core.logging import get_logger
from app.domains.stock.models.company import Company

logger = get_logger(__name__)

INGESTION_KIND = "ingestion"
# How long a client is asked to wait before retrying a scheduled ingestion.
RETRY_AFTER_SECONDS = "30"


def ingestion_pending(ticker: str) -> HTTPException:
    """The honest answer for a ticker that is not tracked *yet*.

    ``None`` from :func:`get_or_schedule_missing` does not mean "no such
    company" and must never be rendered as one (audit U01: missing must not
    look like zero/absent), so the 404 carries an explicit retry hint.
    """
    return HTTPException(
        status_code=404,
        detail=(
            f"{ticker.upper()} is not tracked yet; ingestion has started. "
            "Retry in a moment."
        ),
        headers={"Retry-After": RETRY_AFTER_SECONDS},
    )


async def _reserve_ingestion(db: AsyncSession, symbol: str) -> str:
    """Reserve (or reuse) the single durable ingestion job for ``symbol``.

    Cross-process coalescing: the insert races on the unique
    ``(scope, key)`` constraint, so concurrent requests never each start their
    own provider pipeline. Failed jobs are reported to the caller rather than
    re-queued by polling. Completed jobs can ingest a removed ticker again.
    """
    scope, key = f"ticker:{symbol}", INGESTION_KIND
    fingerprint = hashlib.sha256(
        json.dumps({"ticker": symbol}, sort_keys=True).encode()
    ).hexdigest()
    job_id = str(uuid.uuid4())

    result = await db.execute(
        insert(WorkJob)
        .values(
            id=job_id,
            kind=INGESTION_KIND,
            scope=scope,
            key=key,
            fingerprint=fingerprint,
            payload={"ticker": symbol},
            response={},
            status="queued",
        )
        .on_conflict_do_nothing(constraint="uq_work_jobs_scope_key")
        .returning(WorkJob.id)
    )

    if result.scalar_one_or_none() is not None:
        # Commit now: the request answers 404 without doing any further work,
        # and the reservation must already survive a process exit.
        await db.commit()
        logger.info("Scheduled ingestion for untracked ticker %s", symbol)
        return job_id

    existing = (
        await db.execute(
            select(WorkJob).where(WorkJob.scope == scope, WorkJob.key == key)
        )
    ).scalar_one()
    if existing.status == "failed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Import failed for {symbol}. Check the ticker symbol. "
                "The data provider may not support it or may be unavailable."
            ),
        )
    if existing.status == "completed":
        existing.status = "queued"
        existing.fingerprint = fingerprint
        await db.commit()
    return existing.id


async def get_or_schedule_missing(
    ticker: str, db: AsyncSession
) -> Optional[Company]:
    """Return the tracked company, or schedule ingestion and return ``None``.

    Performs no provider or compute work, so a first-time ticker costs one
    indexed read plus one durable insert instead of a multi-minute request.
    """
    symbol = ticker.upper()
    company = (
        await db.execute(select(Company).where(Company.ticker == symbol))
    ).scalar_one_or_none()
    if company is not None:
        return company

    await _reserve_ingestion(db, symbol)
    return None


async def ingest_missing_ticker(
    ticker: str, db: AsyncSession
) -> Optional[Company]:
    """Run the first-time provider + scoring pipeline for one ticker.

    Called only by the queue worker (``app.workers.jobs``), never from a
    request handler. Stages are best-effort: a fundamentals or news failure
    must not discard prices that already landed, so each stage is guarded
    independently.
    """
    from app.domains.stock.ingestion.fundamentals import FundamentalsIngestion
    from app.domains.stock.ingestion.market import MarketDataIngestion
    from app.domains.stock.ingestion.news import NewsIngestion
    from app.domains.stock.config import get_stock_config
    from app.domains.stock.providers.fmp import FMPProvider

    try:
        # 1. Ingest historical prices (creates the company record)
        market = MarketDataIngestion(
            db,
            fallback=FMPProvider() if get_stock_config().FMP_API_KEY else None,
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=365)
        await market.ingest_historical_prices(ticker, start, end, "1d")

        # 2. Ingest company profile + financial statements
        try:
            fundamentals = FundamentalsIngestion(db)
            await fundamentals.ingest_company_profile(ticker)
            await fundamentals.ingest_fmp_statements(ticker)
        except Exception:
            logger.exception("Optional fundamentals ingestion failed for %s", ticker)
            await db.rollback()

        # 3. Ingest recent news
        try:
            news = NewsIngestion(db)
            await news.ingest_company_news(ticker, limit=50)
        except Exception:
            logger.exception("Optional news ingestion failed for %s", ticker)
            await db.rollback()

        # 3b. Detect market events from the ingested news so the Market
        # Overview "Major Events" panel has data without waiting for the
        # hourly scheduler. 7-day window: auto-ingested news can be days old.
        try:
            from app.domains.stock.scoring.event_detection import EventIntelligenceEngine

            company = (await db.execute(
                select(Company).where(Company.ticker == ticker.upper())
            )).scalar_one_or_none()
            if company:
                event_engine = EventIntelligenceEngine(db)
                await event_engine.detect_events_from_news(company.id, hours=168)
        except Exception:
            logger.exception("Optional event detection ingestion failed for %s", ticker)
            await db.rollback()

        # 4. Compute derived data (technical indicators + financial metrics)
        try:
            from app.domains.stock.scoring.fundamental_analysis import FundamentalAnalysisEngine
            from app.domains.stock.scoring.technical_analysis import TechnicalAnalysisEngine

            company = (await db.execute(
                select(Company).where(Company.ticker == ticker.upper())
            )).scalar_one_or_none()
            if company:
                await TechnicalAnalysisEngine(db).calculate_indicators(company.id)
                await FundamentalAnalysisEngine(db).calculate_and_store(company.id)
        except Exception:
            logger.exception("Optional derived data ingestion failed for %s", ticker)
            await db.rollback()

        result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        return result.scalar_one_or_none()
    except Exception:
        logger.exception("Ticker ingestion failed for %s; checking persisted company", ticker)
        await db.rollback()
        # Earlier stages commit independently. Preserve that usable company
        # instead of reporting a missing record after a later-stage failure.
        result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = result.scalar_one_or_none()
        if company is None:
            raise
        return company
