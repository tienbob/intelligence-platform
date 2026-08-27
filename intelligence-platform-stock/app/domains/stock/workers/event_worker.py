"""
Event detection worker (Section 41).

Every 15 minutes: Detect market anomalies.

Every hour: Analyze important events.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.models.alert import Alert
from app.domains.stock.models.analysis import AnomalyScore
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.scoring.event_detection import (
    AnomalyDetectionEngine,
    EventIntelligenceEngine,
)

logger = get_logger(__name__)


async def _create_anomaly_alerts(session) -> int:
    """Create alerts for recently triggered anomalies that are not yet alerted."""

    result = await session.execute(
        select(AnomalyScore, Company)
        .join(Company, Company.id == AnomalyScore.company_id)
        .where(AnomalyScore.triggered.is_(True))
        .order_by(AnomalyScore.timestamp.desc())
        .limit(50)
    )

    count = 0

    try:
        for anomaly, company in result.all():
            existing = await session.execute(
                select(Alert).where(
                    Alert.company_id == company.id,
                    Alert.alert_type == "PRICE_ANOMALY",
                    Alert.data["anomaly_id"].astext == str(anomaly.id),
                )
            )

            if existing.scalar_one_or_none() is not None:
                continue

            session.add(
                Alert(
                    company_id=company.id,
                    alert_type="PRICE_ANOMALY",
                    severity=(
                        "high"
                        if anomaly.overall_score >= 80
                        else "medium"
                    ),
                    message=(
                        f"{company.ticker} price anomaly detected "
                        f"(score {anomaly.overall_score:.0f})"
                    ),
                    data={
                        "anomaly_id": anomaly.id,
                        "score": anomaly.overall_score,
                    },
                )
            )

            count += 1

        await session.commit()

    except Exception:
        await session.rollback()
        raise

    return count


async def _create_event_alerts(session) -> int:
    """Create alerts for high-materiality events that are not yet alerted."""

    result = await session.execute(
        select(MarketEvent, Company)
        .join(Company, Company.id == MarketEvent.company_id)
        .where(MarketEvent.effective_weight >= 0.4)
        .order_by(MarketEvent.event_date.desc())
        .limit(50)
    )

    count = 0

    try:
        for event, company in result.all():
            existing = await session.execute(
                select(Alert).where(
                    Alert.company_id == company.id,
                    Alert.alert_type == "MARKET_EVENT",
                    Alert.data["event_id"].astext == str(event.id),
                )
            )

            if existing.scalar_one_or_none() is not None:
                continue

            session.add(
                Alert(
                    company_id=company.id,
                    alert_type="MARKET_EVENT",
                    severity=(
                        "high"
                        if event.impact == "negative"
                        else "medium"
                    ),
                    message=(
                        f"{company.ticker}: "
                        f"{event.event_type} "
                        f"({(event.description or '')[:80]})"
                    ),
                    data={
                        "event_id": event.id,
                        "impact_score": event.impact_score,
                        "materiality": event.materiality_score,
                    },
                )
            )

            count += 1

        await session.commit()

    except Exception:
        await session.rollback()
        raise

    return count


async def detect_anomalies() -> None:
    """Detect market anomalies for all tracked companies, then alert on triggers."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).limit(100)
        )
        companies = result.scalars().all()

        engine = AnomalyDetectionEngine(session)

        for company in companies:
            ticker = company.ticker

            try:
                await engine.detect_anomalies(company.id)

            except Exception as exc:
                # The engine may have failed after issuing a DB statement.
                # Reset the transaction before processing the next company.
                await session.rollback()

                logger.exception(
                    "Failed to detect anomalies for %s: %s",
                    ticker,
                    exc,
                )

        try:
            alerted = await _create_anomaly_alerts(session)

        except Exception as exc:
            logger.exception(
                "Failed to create anomaly alerts: %s",
                exc,
            )
            alerted = 0

        logger.info(
            "Anomaly detection complete for %d companies; %d alerts",
            len(companies),
            alerted,
        )


async def analyze_events() -> None:
    """Analyze important events for all tracked companies, then alert on material ones."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).limit(50)
        )
        companies = result.scalars().all()

        engine = EventIntelligenceEngine(session)

        for company in companies:
            ticker = company.ticker

            try:
                # Seven-day window ensures news ingested by
                # _auto_ingest_ticker, which can span several days,
                # remains eligible for event detection.
                await engine.detect_events_from_news(
                    company.id,
                    hours=168,
                )

            except Exception as exc:
                await session.rollback()

                logger.exception(
                    "Failed to analyze events for %s: %s",
                    ticker,
                    exc,
                )

        try:
            alerted = await _create_event_alerts(session)

        except Exception as exc:
            logger.exception(
                "Failed to create event alerts: %s",
                exc,
            )
            alerted = 0

        logger.info(
            "Event analysis complete for %d companies; %d alerts",
            len(companies),
            alerted,
        )