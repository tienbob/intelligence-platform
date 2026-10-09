"""
Data provenance tracking (Section 12).

Every important data point should contain:
    source
    source_id
    retrieved_at
    published_at
    data_version

This allows the system to answer: "Where did this number come from?"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


# Source hierarchy (Section 59)
SOURCE_PRIORITY = {
    "sec": 1,        # Official source — highest priority
    "fred": 1,       # Official source — highest priority
    "twelve_data": 2,
    "massive": 2,    # Verified provider
    "fmp": 3,        # Verified provider
    "finnhub": 4,    # Secondary provider
    "alpha vantage": 4,
    "newsapi": 5,    # General news
}


def get_source_priority(source: str) -> int:
    """Return the priority rank of a source (lower = more authoritative)."""
    if not source:
        return 99
    return SOURCE_PRIORITY.get(source.strip().lower(), 99)


def build_provenance(
    source: str,
    source_id: str | None = None,
    published_at: datetime | None = None,
    data_version: str = "1.0",
) -> dict[str, Any]:
    """
    Build a provenance metadata dict for a data point.

    Example (Section 12):
        {
            "source": "SEC",
            "source_id": "filing-123",
            "published_at": "2026-07-30",
            "retrieved_at": "2026-08-04T08:00:00Z",
            "data_version": "1.0"
        }
    """
    return {
        "source": source,
        "source_id": source_id,
        "published_at": published_at.isoformat() if published_at else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "data_version": data_version,
    }


def select_best_source(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """
    When multiple providers provide the same information, select the best source.

    Hierarchy (Section 59):
        Primary source → Official source → Verified provider → Secondary provider
    """
    if not sources:
        return {}

    def sort_key(s: dict[str, Any]) -> int:
        return get_source_priority(s.get("source", ""))

    return sorted(sources, key=sort_key)[0]


def verify_source_agreement(
    sources: list[dict[str, Any]],
    value_key: str,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """
    Check agreement between multiple sources for the same data point.

    Returns agreement metadata for confidence scoring (Section 61).
    """
    if not sources:
        return {"agreement": 0, "source_count": 0, "confidence_adjustment": 0}

    values = [s.get(value_key) for s in sources if s.get(value_key) is not None]
    if not values:
        return {"agreement": 0, "source_count": 0, "confidence_adjustment": 0}

    if len(values) == 1:
        return {"agreement": 1.0, "source_count": 1, "confidence_adjustment": 0}

    avg = sum(values) / len(values)
    max_diff = max(abs(v - avg) for v in values)

    agreement = 1.0 if avg == 0 else max(0, 1.0 - (max_diff / abs(avg)))
    if agreement > 1 - tolerance:
        agreement = 1.0

    # More sources with high agreement → higher confidence
    confidence_adjustment = (len(values) - 1) * 0.05 * agreement

    return {
        "agreement": round(agreement, 4),
        "source_count": len(values),
        "confidence_adjustment": round(confidence_adjustment, 4),
        "values": values,
    }