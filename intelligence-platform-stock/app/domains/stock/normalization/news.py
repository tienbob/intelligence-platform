"""
News normalization — converts provider-specific news to canonical schema.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def normalize_news(raw: dict[str, Any], provider: str = "massive") -> dict[str, Any]:
    """Normalize a raw news item from any provider."""
    title = raw.get("title", "")
    url = raw.get("url")
    published_at = raw.get("published_at")

    # Parse published_at
    if isinstance(published_at, (int, float)):
        if published_at > 1e12:
            published_dt = datetime.fromtimestamp(published_at / 1000, tz=timezone.utc)
        else:
            published_dt = datetime.fromtimestamp(published_at, tz=timezone.utc)
    elif isinstance(published_at, str):
        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    else:
        published_dt = datetime.now(timezone.utc)

    content_hash = hashlib.sha256(
        f"{title}|{url or ''}|{published_dt.isoformat()}".encode()
    ).hexdigest()

    return {
        "external_id": str(raw.get("external_id", "")),
        "source": raw.get("source", provider),
        "title": title,
        "url": url,
        "published_at": published_dt,
        "summary": raw.get("summary"),
        "content": raw.get("content"),
        "language": "en",
        "content_hash": content_hash,
        "sentiment": raw.get("sentiment"),
        "tickers": raw.get("tickers", []),
    }