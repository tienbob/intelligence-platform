"""
Price normalization — converts provider-specific price data to canonical schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_price_point(raw: dict[str, Any], source: str = "massive") -> dict[str, Any]:
    """
    Normalize a raw price point from any provider into canonical schema.

    Handles timestamp formats from different providers:
        - Unix milliseconds (Massive)
        - Unix seconds (Finnhub)
        - ISO string (FMP)
    """
    ts = raw.get("timestamp")
    if isinstance(ts, (int, float)):
        # Massive uses ms, Finnhub uses seconds
        if ts > 1e12:
            ts = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        ts = datetime.now(timezone.utc)

    return {
        "timestamp": ts,
        "open": float(raw.get("open", 0)),
        "high": float(raw.get("high", 0)),
        "low": float(raw.get("low", 0)),
        "close": float(raw.get("close", 0)),
        "adjusted_close": float(raw["adjusted_close"]) if raw.get("adjusted_close") else None,
        "volume": int(raw.get("volume", 0)),
        "source": source,
    }