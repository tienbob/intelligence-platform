"""
Materiality scoring and time-decay service (Sections 45-46).

Section 45 — News Materiality:
    effective_weight = relevance × credibility × materiality × time_decay

Section 46 — News Time Decay:
    The exact decay function is configurable by event type.
    Recent news has greater influence on current analysis.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.core.logging import get_logger
from app.domains.stock.normalization.events import EVENT_MATERIALITY_WEIGHTS

logger = get_logger(__name__)

# Default half-life (in days) for time decay by event type.
# Higher-impact events decay slower (investors remember them longer).
DEFAULT_HALF_LIFE_DAYS: dict[str, float] = {
    "EARNINGS_BEAT": 30.0,
    "EARNINGS_MISS": 30.0,
    "EARNINGS_IN_LINE": 14.0,
    "REGULATORY": 45.0,
    "PRODUCT_LAUNCH": 21.0,
    "MA": 60.0,
    "MANAGEMENT_CHANGE": 21.0,
    "GUIDANCE_UPDATE": 30.0,
    "DIVIDEND_CHANGE": 21.0,
    "STOCK_SPLIT": 14.0,
    "BUYBACK": 21.0,
    "MACRO_EVENT": 7.0,
    "SECTOR_EVENT": 14.0,
    "INSIDER_TRADING": 14.0,
    "INSTITUTIONAL_CHANGE": 14.0,
    "ANALYST": 7.0,
    "SUPPLY_CHAIN": 14.0,
    "LEGAL": 45.0,
    "OTHER": 3.0,
}

DEFAULT_HALF_LIFE = 7.0  # fallback


def time_decay(
    published_at: datetime,
    event_type: str | None = None,
    now: datetime | None = None,
) -> float:
    """
    Calculate time decay factor (0..1) for a news/event item.

    Uses exponential decay: decay = 0.5 ^ (age_days / half_life)

    Section 46: "The exact decay function should be configurable by event type."
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure timezone-aware
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age = now - published_at
    age_days = max(0.0, age.total_seconds() / 86400.0)

    half_life = DEFAULT_HALF_LIFE_DAYS.get(event_type or "", DEFAULT_HALF_LIFE)

    if age_days == 0:
        return 1.0

    decay = 0.5 ** (age_days / half_life)
    return max(0.0, min(1.0, decay))


def compute_effective_weight(
    relevance: float,
    credibility: float,
    materiality: float,
    decay: float,
) -> float:
    """
    Compute effective weight for a news item (Section 45).

    effective_weight = relevance × credibility × materiality × time_decay

    All inputs are 0..1, output is 0..1.
    """
    weight = relevance * credibility * materiality * decay
    return round(max(0.0, min(1.0, weight)), 4)


def compute_materiality(
    event_type: str,
    sentiment_magnitude: float = 0.0,
    confidence: float = 0.5,
) -> float:
    """
    Compute materiality score for an event (Section 45).

    Materiality reflects how much a news item is likely to
    materially affect a company's fundamentals or stock price.

    Args:
        event_type: Canonical event type string.
        sentiment_magnitude: Abs value of sentiment (0..1).
        confidence: Confidence in the classification (0..1).

    Returns:
        materiality score 0..1
    """
    base = EVENT_MATERIALITY_WEIGHTS.get(event_type, 0.20)
    # Blend base weight with sentiment magnitude and confidence
    materiality = base * (0.6 + 0.2 * sentiment_magnitude + 0.2 * confidence)
    return round(max(0.0, min(1.0, materiality)), 4)


def rank_events_by_materiality(
    events: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """
    Rank events by effective weight (materiality × time_decay).

    Section 45-46: Recent, high-materiality events rank higher.

    Args:
        events: List of event dicts with keys:
            event_type, event_date, relevance_score, credibility_score,
            sentiment, confidence
        now: Reference timestamp (defaults to UTC now)

    Returns:
        Events sorted by effective_weight descending, with
        'materiality_score', 'time_decay', and 'effective_weight' added.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    ranked = []
    for event in events:
        event_type = event.get("event_type", "OTHER")
        published_at = event.get("event_date") or event.get("published_at")
        if published_at is None:
            continue

        relevance = event.get("relevance_score", 0.5)
        credibility = event.get("credibility_score", 0.7)
        sentiment = event.get("sentiment", 0.0)
        confidence = event.get("confidence", 0.5)

        sentiment_mag = abs(sentiment) if sentiment is not None else 0.0
        materiality = compute_materiality(event_type, sentiment_mag, confidence)
        decay = time_decay(published_at, event_type, now)
        weight = compute_effective_weight(relevance, credibility, materiality, decay)

        ranked.append({
            **event,
            "materiality_score": materiality,
            "time_decay": round(decay, 4),
            "effective_weight": weight,
        })

    ranked.sort(key=lambda e: e.get("effective_weight", 0), reverse=True)
    return ranked