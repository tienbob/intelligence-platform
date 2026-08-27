"""
Data freshness validation (Section 18).

Data must be classified by freshness:
    REAL_TIME       ≤ 60 seconds
    NEAR_REAL_TIME  ≤ 5 minutes
    DELAYED         ≤ 15 minutes
    DAILY           ≤ 24 hours
    QUARTERLY       ≤ 90 days
    ANNUAL          ≤ 365 days
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers import DataFreshness

logger = get_logger(__name__)
settings = get_stock_config()


def classify_freshness(data_age_seconds: float) -> DataFreshness:
    """Classify data freshness based on age in seconds."""
    if data_age_seconds <= settings.REAL_TIME_MAX_AGE_SEC:
        return DataFreshness.REAL_TIME
    elif data_age_seconds <= settings.NEAR_REAL_TIME_MAX_AGE_SEC:
        return DataFreshness.NEAR_REAL_TIME
    elif data_age_seconds <= settings.DELAYED_MAX_AGE_SEC:
        return DataFreshness.DELAYED
    elif data_age_seconds <= settings.DAILY_MAX_AGE_SEC:
        return DataFreshness.DAILY
    elif data_age_seconds <= 86400 * 90:
        return DataFreshness.QUARTERLY
    else:
        return DataFreshness.ANNUAL


def check_freshness(
    retrieved_at: datetime,
    expected_freshness: DataFreshness = DataFreshness.DAILY,
) -> bool:
    """
    Check whether data is fresh enough for the expected freshness level.

    Returns True if the data age is within the acceptable range.
    """
    now = datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)

    age_seconds = (now - retrieved_at).total_seconds()

    thresholds = {
        DataFreshness.REAL_TIME: settings.REAL_TIME_MAX_AGE_SEC,
        DataFreshness.NEAR_REAL_TIME: settings.NEAR_REAL_TIME_MAX_AGE_SEC,
        DataFreshness.DELAYED: settings.DELAYED_MAX_AGE_SEC,
        DataFreshness.DAILY: settings.DAILY_MAX_AGE_SEC,
        DataFreshness.QUARTERLY: 86400 * 90,
        DataFreshness.ANNUAL: 86400 * 365,
    }

    max_age = thresholds.get(expected_freshness, settings.DAILY_MAX_AGE_SEC)
    is_fresh = age_seconds <= max_age

    if not is_fresh:
        logger.warning(
            "Data freshness check failed: age=%.0fs, max=%ds, expected=%s",
            age_seconds,
            max_age,
            expected_freshness.value,
        )

    return is_fresh


def get_data_age(retrieved_at: datetime) -> dict[str, float | str]:
    """Return data age information for observability."""
    now = datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)

    age_seconds = (now - retrieved_at).total_seconds()
    freshness = classify_freshness(age_seconds)

    return {
        "age_seconds": age_seconds,
        "freshness": freshness.value,
        "is_fresh": age_seconds <= settings.DAILY_MAX_AGE_SEC,
    }