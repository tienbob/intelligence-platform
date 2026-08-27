"""
Event detection and anomaly detection (Sections 22–23, 26).

Detects:
    Large price movement, Volume spike, Volatility spike,
    Technical breakout, Technical breakdown, Unusual trading activity

Event intelligence connects:
    Price ↔ News, Price ↔ Earnings, Price ↔ Macro,
    Price ↔ Company Events, Historical Event Comparison

Phase 4 (#157): End-to-end event classification, impact scoring,
materiality ranking, dedup, and automatic price correlation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.models.analysis import AnomalyScore
from app.domains.stock.models.event import EventPriceCorrelation, MarketEvent
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.normalization.events import classify_event, score_event_impact
from app.domains.stock.scoring.materiality import compute_effective_weight, time_decay

logger = get_logger(__name__)
settings = get_stock_config()


class AnomalyDetectionEngine:
    """
    Detects market anomalies (Section 22).

    movement_score =
        price_change_score * 0.35
        + volume_score * 0.25
        + volatility_score * 0.20
        + technical_score * 0.20

    If movement_score >= 80, trigger deeper investigation.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_recent_prices(
        self, company_id: int, days: int = 30
    ) -> list[StockPrice]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= since)
            .order_by(StockPrice.timestamp)
        )
        return list(result.scalars().all())

    @staticmethod
    def _price_change_score(prices: list[StockPrice]) -> float:
        """Calculate price change score (0-100)."""
        if len(prices) < 2:
            return 0
        latest = prices[-1]
        prev = prices[-2]
        if prev.close == 0:
            return 0
        change_pct = abs((latest.close - prev.close) / prev.close) * 100
        # Scale: 1% = 20 points, 5% = 60, 10%+ = 100
        return min(100, change_pct * 20)

    @staticmethod
    def _volume_score(prices: list[StockPrice]) -> float:
        """Calculate volume anomaly score (0-100)."""
        if len(prices) < 21:
            return 0
        avg_vol = sum(p.volume for p in prices[-21:-1]) / 20
        latest_vol = prices[-1].volume
        if avg_vol == 0:
            return 0
        ratio = latest_vol / avg_vol
        # 2x volume = 50, 3x = 75, 5x+ = 100
        return min(100, max(0, (ratio - 1) * 25))

    @staticmethod
    def _volatility_score(prices: list[StockPrice]) -> float:
        """Calculate volatility spike score (0-100)."""
        if len(prices) < 21:
            return 0
        recent_returns = []
        for i in range(1, min(6, len(prices))):
            if prices[i - 1].close > 0:
                recent_returns.append(abs(prices[i].close - prices[i - 1].close) / prices[i - 1].close)

        baseline_returns = []
        for i in range(1, min(21, len(prices))):
            if prices[i - 1].close > 0:
                baseline_returns.append(abs(prices[i].close - prices[i - 1].close) / prices[i - 1].close)

        if not recent_returns or not baseline_returns:
            return 0

        recent_vol = sum(recent_returns) / len(recent_returns)
        baseline_vol = sum(baseline_returns) / len(baseline_returns)

        if baseline_vol == 0:
            return 0

        ratio = recent_vol / baseline_vol
        return min(100, max(0, (ratio - 1) * 50))

    @staticmethod
    def _technical_score(prices: list[StockPrice]) -> float:
        """Calculate technical breakout/breakdown score (0-100)."""
        if len(prices) < 20:
            return 0
        closes = [p.close for p in prices]
        sma_20 = sum(closes[-20:]) / 20
        latest = closes[-1]

        if sma_20 == 0:
            return 0

        deviation = abs((latest - sma_20) / sma_20) * 100
        # 2% deviation = 40, 5% = 80, 8%+ = 100
        return min(100, deviation * 12.5)

    async def detect_anomalies(self, company_id: int) -> AnomalyScore | None:
        """Detect anomalies for a company and store the score."""
        prices = await self._get_recent_prices(company_id)
        if len(prices) < 2:
            return None

        price_score = self._price_change_score(prices)
        vol_score = self._volume_score(prices)
        vola_score = self._volatility_score(prices)
        tech_score = self._technical_score(prices)

        movement_score = (
            price_score * settings.PRICE_CHANGE_SCORE_WEIGHT
            + vol_score * settings.VOLUME_SCORE_WEIGHT
            + vola_score * settings.VOLATILITY_SCORE_WEIGHT
            + tech_score * settings.TECHNICAL_SCORE_WEIGHT
        )

        triggered = movement_score >= settings.ANOMALY_MOVEMENT_THRESHOLD

        anomaly = AnomalyScore(
            company_id=company_id,
            timestamp=datetime.now(timezone.utc),
            price_change_score=price_score,
            volume_score=vol_score,
            volatility_score=vola_score,
            technical_score=tech_score,
            overall_score=movement_score,
            triggered=triggered,
        )
        self.session.add(anomaly)
        await self.session.commit()

        if triggered:
            logger.warning(
                "Anomaly triggered for company_id=%d: score=%.1f",
                company_id,
                movement_score,
            )

        return anomaly


class EventIntelligenceEngine:
    """
    Connects price movements to events (Section 23, 26).

    Price ↔ News, Price ↔ Earnings, Price ↔ Macro, Price ↔ Company Events

    Phase 4: End-to-end event classification with:
    - Impact scoring and materiality
    - Dedup via unique constraint (company_id, source_news_id)
    - Automatic price correlation
    - Effective weight calculation (Section 45-46)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def correlate_event_with_price(
        self, event: MarketEvent, company_id: int
    ) -> EventPriceCorrelation | None:
        """
        Record the market response to an important event (Section 26).

        Uses day-based windows for daily bar data:
        - price_before: last close on or before the event date
        - price_after: first close on or after event_date + 1 day

        Stores: price_before, price_after, price_change, volume_change,
                volatility_change, time_to_reaction
        """
        event_time = event.event_date
        # Day-based windows for daily bars
        before_time = event_time  # price on event day
        after_time = event_time + timedelta(days=1)  # price next day

        # Get price before (on or before event date)
        before_result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp <= before_time)
            .order_by(desc(StockPrice.timestamp))
            .limit(1)
        )
        # Get price after (on or after event_date + 1 day)
        after_result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= after_time)
            .order_by(StockPrice.timestamp)
            .limit(1)
        )

        before = before_result.scalar_one_or_none()
        after = after_result.scalar_one_or_none()

        if not before or not after:
            return None

        price_change = ((after.close - before.close) / before.close) if before.close else None
        volume_change = ((after.volume - before.volume) / before.volume) if before.volume else None

        correlation = EventPriceCorrelation(
            event_id=event.id,
            company_id=company_id,
            price_before=before.close,
            price_after=after.close,
            price_change=price_change,
            volume_change=volume_change,
            time_to_reaction_min=int((after.timestamp - event_time).total_seconds() / 60),
        )
        self.session.add(correlation)
        await self.session.commit()
        return correlation

    async def detect_events_from_news(
        self, company_id: int, hours: int = 24
    ) -> list[MarketEvent]:
        """
        Detect events from recent news for a company.

        Phase 4: Enhanced with:
        - Impact scoring and materiality (Section 45)
        - Dedup via upsert (company_id, source_news_id)
        - Effective weight calculation (Section 46)
        - Automatic price correlation for high-materiality events
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        now = datetime.now(timezone.utc)

        result = await self.session.execute(
            select(News, CompanyNews)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company_id)
            .where(News.published_at >= since)
            .order_by(desc(News.published_at))
        )
        rows = result.all()

        events: list[MarketEvent] = []
        for news, cn in rows:
            event_type = classify_event(news.title, news.summary)
            if event_type == "OTHER":
                continue

            # Phase 4: Score impact and materiality
            confidence = cn.confidence or 0.7
            impact_label, impact_score, materiality = score_event_impact(
                event_type,
                sentiment=news.sentiment,
                confidence=confidence,
            )

            # Phase 4: Calculate effective weight (Section 45-46)
            relevance = cn.relevance_score or 0.5
            credibility = news.credibility_score or 0.7
            decay = time_decay(news.published_at, event_type, now)
            effective_weight = compute_effective_weight(
                relevance, credibility, materiality, decay
            )

            # Phase 4: Dedup via INSERT ... ON CONFLICT DO NOTHING.
            # One news article produces one canonical event per company.
            # (unique constraint on company_id, source_news_id)
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            insert_stmt = pg_insert(MarketEvent).values(
                company_id=company_id,
                event_type=event_type,
                event_date=news.published_at,
                impact=impact_label,
                impact_score=impact_score,
                confidence=confidence,
                materiality_score=materiality,
                effective_weight=effective_weight,
                description=news.title,
                source_news_id=news.id,
            ).on_conflict_do_nothing(
                index_elements=["company_id", "source_news_id","event_type"]
            ).returning(MarketEvent.id)

            result = await self.session.execute(insert_stmt)
            row = result.first()
            if row is None:
                continue  # already exists (conflict)

            event = await self.session.get(MarketEvent, row[0])
            if event is None:
                continue
            events.append(event)

        if events:
            await self.session.commit()
            logger.info("Detected %d events for company_id=%d", len(events), company_id)

            # Phase 4: Auto-correlate high-materiality events with price,
            # then re-evaluate impact from the realized market reaction.
            for event in events:
                if event.materiality_score and event.materiality_score >= 0.5:
                    try:
                        correlation = await self.correlate_event_with_price(event, company_id)
                        if correlation is not None:
                            await self._update_impact_from_price(event, correlation)
                    except Exception as exc:
                        logger.warning(
                            "Price correlation failed for event %d: %s",
                            event.id,
                            exc,
                        )

            # Persist the impact re-evaluation performed above.
            await self.session.commit()

        return events

    @staticmethod
    def _update_impact_from_price(event: MarketEvent, correlation: EventPriceCorrelation) -> str:
        """
        Re-evaluate an event's impact using the realized price reaction.

        Sentiment tells us how the article was worded; the price reaction
        tells us what the market actually did. The realized price reaction
        takes precedence because it reflects actual market impact rather
        than linguistic tone.

        Returns the updated impact label.
        """
        price_change = correlation.price_change or 0.0

        # Strong price moves dominate the label regardless of sentiment.
        if price_change >= 0.03:
            impact_label = "positive"
        elif price_change <= -0.03:
            impact_label = "negative"
        elif abs(price_change) < 0.005:
            # No meaningful market reaction — keep the initial label.
            impact_label = event.impact or "neutral"
        else:
            # Small but real reaction — keep the initial label as a tiebreaker.
            impact_label = event.impact or "neutral"

        event.impact = impact_label
        event.impact_score = min(1.0, abs(price_change) * 10)
        return impact_label

    async def get_materiality_ranked_events(
        self, company_id: int, hours: int = 168
    ) -> list[dict[str, Any]]:
        """
        Get events for a company ranked by effective weight (Section 45-46).

        Returns events sorted by effective_weight descending, with
        materiality_score and time_decay included.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        now = datetime.now(timezone.utc)

        result = await self.session.execute(
            select(MarketEvent)
            .where(MarketEvent.company_id == company_id)
            .where(MarketEvent.event_date >= since)
            .order_by(desc(MarketEvent.event_date))
        )
        events = result.scalars().all()

        ranked = []
        for event in events:
            materiality = event.materiality_score or 0.0
            decay = time_decay(event.event_date, event.event_type, now)
            weight = event.effective_weight or compute_effective_weight(
                0.5, 0.7, materiality, decay
            )
            ranked.append({
                "id": event.id,
                "event_type": event.event_type,
                "event_date": event.event_date.isoformat() if event.event_date else None,
                "impact": event.impact,
                "impact_score": event.impact_score,
                "confidence": event.confidence,
                "materiality_score": materiality,
                "time_decay": round(decay, 4),
                "effective_weight": weight,
                "description": event.description,
            })

        ranked.sort(key=lambda e: e.get("effective_weight", 0), reverse=True)
        return ranked