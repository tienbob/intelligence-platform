"""
Ticker query caching service using Redis.

Provides shared caching across workers/processes with proper TTL management.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, List, Dict

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

class RedisTickerCache:
    """
    Redis-based caching for ticker queries.

    Uses Redis SETEX for automatic TTL management and provides
    shared caching across all workers/processes.
    """

    def __init__(self, redis_client: Redis, ttl_seconds: int = 3600):
        """
        Initialize ticker cache.

        Args:
            redis_client: Redis async client
            ttl_seconds: Cache TTL in seconds (default: 3600 = 1 hour)
        """
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    async def get_or_compute(
        self,
        ticker: str,
        query: str,
        compute_func: Callable[[], Any]
    ) -> List[Dict[str, Any]]:
        """
        Get cached results from Redis or compute and cache new ones.

        Args:
            ticker: Ticker symbol
            query: Query string
            compute_func: Function to compute results if not cached

        Returns:
            Cached or freshly computed results
        """
        cache_key = f"ticker_cache:{ticker.upper()}:{hash(query)}"

        # Try to get from Redis
        cached_data = await self.redis.get(cache_key)
        if cached_data:
            try:
                results = json.loads(cached_data)
                logger.debug("Cache hit for ticker %s, query: %s", ticker, query[:50] + "...")
                return results
            except json.JSONDecodeError:
                logger.warning("Invalid cached data for key %s", cache_key)
                # Continue to compute fresh results

        # Compute and cache in Redis with TTL
        logger.debug("Cache miss for ticker %s, computing...", ticker)
        start_time = time.time()
        results = await compute_func()
        compute_time = time.time() - start_time

        # Only cache if results are non-empty and computation was successful
        if results:
            try:
                await self.redis.setex(
                    cache_key,
                    self.ttl_seconds,
                    json.dumps(results)
                )
                logger.debug(
                    "Cached results for ticker %s, compute_time=%.3fs, ttl=%ds",
                    ticker, compute_time, self.ttl_seconds
                )
            except Exception as e:
                logger.error("Failed to cache results for ticker %s: %s", ticker, e)

        return results

    async def invalidate_ticker(self, ticker: str) -> None:
        """
        Invalidate all cache entries for a specific ticker.

        Useful when ticker data is updated.
        """
        # Find all keys for this ticker
        pattern = f"ticker_cache:{ticker.upper()}:*"
        keys = []

        # Use SCAN to find keys (non-blocking)
        cursor = 0
        while True:
            cursor, batch_keys = await self.redis.scan(cursor, pattern)
            keys.extend(batch_keys)
            if cursor == 0:
                break

        # Delete all found keys
        if keys:
            await self.redis.delete(*keys)
            logger.info("Invalidated %d cache entries for ticker %s", len(keys), ticker)

    async def invalidate_all(self) -> None:
        """
        Invalidate all ticker cache entries.

        Use with caution in production.
        """
        # Find all ticker cache keys
        pattern = "ticker_cache:*"
        keys = []

        # Use SCAN to find keys (non-blocking)
        cursor = 0
        while True:
            cursor, batch_keys = await self.redis.scan(cursor, pattern)
            keys.extend(batch_keys)
            if cursor == 0:
                break

        # Delete all found keys
        if keys:
            await self.redis.delete(*keys)
            logger.info("Invalidated %d total ticker cache entries", len(keys))

    async def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics and health metrics.
        """
        # Count total cache entries
        pattern = "ticker_cache:*"
        total_keys = 0

        cursor = 0
        while True:
            cursor, batch_keys = await self.redis.scan(cursor, pattern)
            total_keys += len(batch_keys)
            if cursor == 0:
                break

        # Get Redis memory usage
        info = await self.redis.info("memory")
        used_memory = info.get("used_memory", 0)
        used_memory_human = info.get("used_memory_human", "unknown")

        return {
            "total_ticker_cache_entries": total_keys,
            "redis_used_memory_bytes": used_memory,
            "redis_used_memory_human": used_memory_human,
            "cache_ttl_seconds": self.ttl_seconds,
            "timestamp": time.time()
        }

    async def get_ticker_cache_stats(self, ticker: str) -> dict[str, Any]:
        """
        Get cache statistics for a specific ticker.
        """
        pattern = f"ticker_cache:{ticker.upper()}:*"
        ticker_keys = 0

        cursor = 0
        while True:
            cursor, batch_keys = await self.redis.scan(cursor, pattern)
            ticker_keys += len(batch_keys)
            if cursor == 0:
                break

        return {
            "ticker": ticker,
            "cached_queries": ticker_keys,
            "timestamp": time.time()
        }