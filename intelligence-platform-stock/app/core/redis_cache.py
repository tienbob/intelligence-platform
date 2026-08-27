"""
Redis-backed cache for the provider layer.

When Redis is configured and enabled, provider responses are cached in Redis
with a configurable TTL (default 1 day). If Redis is unavailable, the provider
layer falls back to the in-memory cache so the application never hard-fails
on cache operations.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _json_default(obj: Any) -> Any:
    """JSON serializer fallback for non-serializable types (e.g. datetime)."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class RedisCache:
    """Async-friendly Redis cache wrapper using redis-py (sync client in thread)."""

    def __init__(
        self,
        url: Optional[str] = None,
        prefix: str = "mi:cache:",
        ttl_seconds: int = 86400,
        db: int = 0,
        timeout_sec: float = 2.0,
        enabled: bool = True,
    ):
        self._url = url or settings.REDIS_URL
        self._prefix = prefix or settings.REDIS_CACHE_PREFIX
        self._ttl = ttl_seconds or settings.REDIS_CACHE_TTL_SECONDS
        self._db = db
        self._timeout = timeout_sec
        self._enabled = enabled and bool(self._url)
        self._client = None
        self._available: Optional[bool] = None  # None=unknown, True/False

    @property
    def available(self) -> bool:
        """Whether Redis is configured and reachable."""
        if self._available is None:
            self._check_connection()
        return bool(self._available)

    def _check_connection(self) -> None:
        if not self._enabled:
            self._available = False
            return
        try:
            import redis  # type: ignore

            client = redis.Redis.from_url(
                self._url,
                db=self._db,
                socket_timeout=self._timeout,
                socket_connect_timeout=self._timeout,
                decode_responses=True,
            )
            client.ping()
            self._client = client
            self._available = True
        except Exception as exc:  # pragma: no cover - depends on env
            logger.warning("Redis unavailable, falling back to in-memory cache: %s", exc)
            self._available = False

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Fetch a value from Redis. Returns None on miss or any Redis error."""
        if not self.available:
            return None
        try:
            raw = self._client.get(self._key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis get failed for %s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value in Redis with TTL. No-op on any Redis error."""
        if not self.available:
            return
        try:
            ttl = ttl_seconds or self._ttl
            self._client.set(self._key(key), json.dumps(value, default=_json_default), ex=ttl)
        except Exception as exc:
            logger.warning("Redis set failed for %s: %s", key, exc)

    async def clear(self) -> None:
        """Clear all cached keys (scoped to this prefix)."""
        if not self.available:
            return
        try:
            keys = self._client.keys(f"{self._prefix}*")
            if keys:
                self._client.delete(*keys)
        except Exception as exc:
            logger.warning("Redis clear failed: %s", exc)


# Module-level singleton so all providers share one Redis connection.
_redis_cache_instance: Optional[RedisCache] = None


def get_redis_cache() -> RedisCache:
    """Return a shared RedisCache instance."""
    global _redis_cache_instance
    if _redis_cache_instance is None:
        _redis_cache_instance = RedisCache(
            url=settings.REDIS_URL,
            prefix=settings.REDIS_CACHE_PREFIX,
            ttl_seconds=settings.REDIS_CACHE_TTL_SECONDS,
            db=settings.REDIS_CACHE_DB,
            timeout_sec=settings.REDIS_CACHE_TIMEOUT_SEC,
            enabled=settings.REDIS_CACHE_ENABLED,
        )
    return _redis_cache_instance