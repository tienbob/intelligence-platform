"""
Rate limiting (Phase 8, Section 86).

Implements a sliding-window in-memory rate limiter with per-route limits.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

settings = get_settings()


class SlidingWindowRateLimiter:
    """
    Sliding-window rate limiter.

    Tracks request timestamps per (client_id, route) key and rejects
    requests that exceed the configured limit within the window.
    """

    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int | None = None) -> None:
        """
        Check if a request is within the rate limit.

        Raises HTTPException 429 if the limit is exceeded.
        """
        if not settings.RATE_LIMIT_ENABLED:
            return

        max_requests = limit or self.default_limit
        now = time.monotonic()

        async with self._lock:
            window = self._requests[key]
            # Remove expired timestamps
            while window and now - window[0] > self.window_seconds:
                window.popleft()

            if len(window) >= max_requests:
                retry_after = int(self.window_seconds - (now - window[0]))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            window.append(now)

    async def reset(self, key: str) -> None:
        """Reset the rate limit for a key."""
        async with self._lock:
            self._requests[key].clear()


# Global rate limiter instance
rate_limiter = SlidingWindowRateLimiter(
    default_limit=settings.RATE_LIMIT_DEFAULT_PER_MINUTE,
    window_seconds=60,
)


def get_client_key(request: Request) -> str:
    """Extract a client identifier from the request."""
    # Use X-Forwarded-For if behind a proxy, otherwise client host
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(
    request: Request,
    limit: int | None = None,
    scope: str = "default",
) -> None:
    """FastAPI dependency for rate limiting."""
    client = get_client_key(request)
    key = f"{client}:{scope}"
    await rate_limiter.check(key, limit)