"""
Rate limiting (Phase 8, Section 86).

Shared Redis sliding windows with an in-memory fallback for explicit development.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import secrets
import time
from collections import defaultdict, deque

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
                retry_after = max(1, math.ceil(self.window_seconds - (now - window[0])))
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


class RedisRateLimiter:
    """Atomic shared sliding window, using Redis time rather than worker clocks."""

    SCRIPT = """
    local t = redis.call('TIME')
    local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
    local window = tonumber(ARGV[1])
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
    if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
      local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
      return math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
    end
    redis.call('ZADD', KEYS[1], now, ARGV[3])
    redis.call('PEXPIRE', KEYS[1], window)
    return 0
    """

    def __init__(self, url, default_limit=60, window_seconds=60):
        self.url = url
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.client = None

    def connection(self):
        if self.client is None:
            from redis.asyncio import Redis
            self.client = Redis.from_url(self.url, socket_timeout=2, socket_connect_timeout=2)
        return self.client

    def storage_key(self, key):
        return 'mi:rate:' + hashlib.sha256(key.encode()).hexdigest()

    async def check(self, key, limit=None):
        if not settings.RATE_LIMIT_ENABLED:
            return
        from redis.exceptions import RedisError
        try:
            retry = await self.connection().eval(
                self.SCRIPT, 1, self.storage_key(key), self.window_seconds * 1000,
                limit or self.default_limit, secrets.token_hex(16),
            )
        except RedisError as exc:
            # Paid work must not bypass its shared budget during an outage.
            raise HTTPException(503, 'Rate-limit service unavailable. Please retry.',
                                headers={'Retry-After': '5'}) from exc
        if retry:
            raise HTTPException(429, 'Rate limit exceeded.', headers={'Retry-After': str(retry)})

    async def reset(self, key):
        await self.connection().delete(self.storage_key(key))


# Redis is independent of the optional provider-cache feature flag.
rate_limiter = (
    RedisRateLimiter(settings.REDIS_URL, settings.RATE_LIMIT_DEFAULT_PER_MINUTE)
    if settings.REDIS_URL else
    SlidingWindowRateLimiter(settings.RATE_LIMIT_DEFAULT_PER_MINUTE)
)


def get_client_key(request: Request) -> str:
    # Trust gateway identity only with the service credential. Forwarded IP
    # headers from arbitrary callers must not permit changing the quota key.
    supplied = request.headers.get('X-Service-Key', '')
    trusted = bool(settings.INTERNAL_SERVICE_KEY) and secrets.compare_digest(
        supplied, settings.INTERNAL_SERVICE_KEY or '')
    user_id = request.headers.get('X-User-Id')
    if trusted and user_id and user_id.isdecimal():
        return f'user:{user_id}'
    return request.client.host if request.client else 'unknown'


async def rate_limit(request: Request, limit: int | None = None, scope: str = 'default') -> None:
    if settings.RATE_LIMIT_ENABLED and not settings.REDIS_URL and settings.ENVIRONMENT != 'development':
        raise HTTPException(503, 'Shared rate limiting is not configured.', headers={'Retry-After': '5'})
    await rate_limiter.check(f'{get_client_key(request)}:{scope}', limit)
