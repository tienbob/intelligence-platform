"""
News processing worker (Section 41).

Every 5–15 minutes: Process important news.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.ingestion.news import NewsIngestion
from app.domains.stock.models.company import Company
from app.domains.stock.models.news import News
from app.domains.stock.scoring.event_detection import EventIntelligenceEngine
from app.domains.stock.scoring.materiality import (
    compute_effective_weight,
    compute_materiality,
    time_decay,
)
from app.domains.stock.scoring.sentiment import SentimentAnalyzer


logger = get_logger(__name__)


async def _enrich_news_scores(
    session,
) -> int:
    """Compute sentiment/credibility/impact/materiality scores."""

    analyzer = SentimentAnalyzer()

    result = await session.execute(
        select(News).where(
            News.sentiment.is_(None)
        )
    )

    news = result.scalars().all()

    for n in news:
        s = analyzer.analyze_news(
            n.summary or n.title or "",
            n.source or "",
            "",
        )

        n.sentiment = s["sentiment"]
        n.relevance_score = s["relevance_score"]
        n.credibility_score = s["credibility_score"]
        n.magnitude_score = s["magnitude"]
        n.impact_score = s["impact_score"]
        n.confidence_score = s["confidence_score"]

        materiality = compute_materiality(
            "NEWS",
            abs(s["sentiment"]),
            s["confidence_score"],
        )

        n.materiality_score = materiality

        n.effective_weight = compute_effective_weight(
            s["relevance_score"],
            s["credibility_score"],
            materiality,
            time_decay(
                n.published_at,
                "NEWS",
                datetime.now(timezone.utc),
            ),
        )

    await session.commit()

    return len(news)


async def process_news() -> None:
    """
    Process news for all tracked companies, then enrich scores
    and detect events.
    """

    async with async_session_factory() as session:
        # Only load scalar values that are needed by the worker.
        #
        # Avoid keeping Company ORM objects alive while NewsIngestion
        # commits/rolls back against the same AsyncSession.
        result = await session.execute(
            select(
                Company.id,
                Company.ticker,
            ).limit(50)
        )

        companies = result.all()

        ingestion = NewsIngestion(session)

        # ---------------------------------------------------------
        # 1. Ingest news
        # ---------------------------------------------------------

        for company_id, ticker in companies:
            try:
                await ingestion.ingest_company_news(
                    ticker,
                    limit=20,
                )

            except Exception as exc:
                logger.error(
                    "Failed to process news for %s: %s",
                    ticker,
                    exc,
                    exc_info=True,
                )

        # ---------------------------------------------------------
        # 2. Enrich scores
        # ---------------------------------------------------------

        try:
            enriched = await _enrich_news_scores(session)

        except Exception as exc:
            await session.rollback()

            logger.exception(
                "Failed to enrich news scores: %s",
                exc,
            )

            raise

        # ---------------------------------------------------------
        # 3. Detect market events
        # ---------------------------------------------------------

        event_engine = EventIntelligenceEngine(session)

        for company_id, ticker in companies:
            try:
                await event_engine.detect_events_from_news(
                    company_id,
                    hours=168,
                )

            except Exception as exc:
                logger.error(
                    "Failed to detect events for %s: %s",
                    ticker,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "News processing complete for %d companies; "
            "enriched %d items",
            len(companies),
            enriched,
        )