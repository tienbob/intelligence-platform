"""
Provider abstraction layer (Sections 5–6, 17).

The application must not directly depend on one provider. All external data
sources are accessed through abstract interfaces so providers can be swapped
without rewriting the application.

Every provider adapter supports:
    - Rate limiting
    - Exponential backoff
    - Retry
    - Timeout
    - Circuit breaker
    - Caching
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis_cache import get_redis_cache

logger = get_logger(__name__)
settings = get_settings()


# Cache for provider responses (issue #9).
#
# Uses Redis as the shared, persistent backend when enabled (REDIS_CACHE_ENABLED
# and REDIS_URL set). Falls back to a process-local in-memory cache when Redis is
# unavailable so the app never hard-fails on cache operations.
class ResponseCache:
    """Thread-safe cache for provider API responses (Redis-backed when available)."""

    def __init__(self, ttl_seconds: int = 300, use_redis: bool = True):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._redis = get_redis_cache() if use_redis else None

    async def get(self, key: str) -> Any | None:
        # Prefer shared Redis cache when reachable.
        if self._redis is not None and self._redis.available:
            value = await self._redis.get(key)
            if value is not None:
                return value

        # In-memory fallback.
        async with self._lock:
            if key in self._cache:
                value, expires_at = self._cache[key]
                if asyncio.get_running_loop().time() < expires_at:
                    return value
                del self._cache[key]
            return None

    async def set(self, key: str, value: Any) -> None:
        # Prefer shared Redis cache when reachable.
        if self._redis is not None and self._redis.available:
            await self._redis.set(key, value, ttl_seconds=self._ttl)

        # In-memory fallback.
        async with self._lock:
            expires_at = asyncio.get_running_loop().time() + self._ttl
            self._cache[key] = (value, expires_at)

    async def clear(self) -> None:
        if self._redis is not None and self._redis.available:
            await self._redis.clear()
        async with self._lock:
            self._cache.clear()


class DataFreshness(str, Enum):
    """Data freshness classification (Section 18)."""

    REAL_TIME = "real_time"
    NEAR_REAL_TIME = "near_real_time"
    DELAYED = "delayed"
    DAILY = "daily"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, provider: str, message: str, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")


class RateLimitError(ProviderError):
    """Raised when a provider returns 429 Too Many Requests."""

    def __init__(self, provider: str, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__(provider, "Rate limit exceeded", 429)


class CircuitBreakerOpenError(ProviderError):
    """Raised when the circuit breaker is open."""

    def __init__(self, provider: str):
        super().__init__(provider, "Circuit breaker open")


class CircuitBreaker:
    """
    Simple circuit breaker for provider calls.

    States:
        CLOSED   — requests flow normally
        OPEN     — requests fail fast
        HALF_OPEN — limited requests to test recovery
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._failure_count = 0
        self._state = "closed"
        self._opened_at: float | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        if self._state == "open":
            if self._opened_at and (asyncio.get_running_loop().time() - self._opened_at) > self.recovery_timeout:
                self._state = "half_open"
                self._half_open_calls = 0
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state in ("open", "half_open"):
            self._state = "closed"
            self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._state == "half_open":
            self._state = "open"
            self._opened_at = asyncio.get_running_loop().time()
        elif self._failure_count >= self.failure_threshold:
            self._state = "open"
            self._opened_at = asyncio.get_running_loop().time()

    def can_call(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open":
            return self._half_open_calls < self.half_open_max_calls
        return False


class BaseProvider(ABC):
    """
    Base class for all data providers.

    Implements HTTP client with retry, rate limiting, exponential backoff,
    timeout, circuit breaker, and caching (Section 17).
    """

    provider_name: str = "base"
    base_url: str = ""
    rate_limit_per_sec: int = 5
    cache_ttl_seconds: int = 86400  # 24 hours default cache TTL

    def __init__(self, api_key: Optional[str] = None, **kwargs: Any):
        self.api_key = api_key
        self._circuit_breaker = CircuitBreaker()
        self._client: httpx.AsyncClient | None = None
        self._cache = ResponseCache(ttl_seconds=self.cache_ttl_seconds)
        # Token-bucket variables for requests-per-second enforcement
        self._rb_tokens: float | None = None
        self._rb_last: float | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers=self._get_headers(),
            )
        return self._client

    def _get_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        """Override in subclasses to inject API keys into query params."""
        return {k: v for k, v in kwargs.items() if v is not None}

    def _validate_response(self, result: Any) -> None:
        """Provider hook: reject API-level errors before caching a response."""

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        max_retries: int = 3,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Make an HTTP request with retry, backoff, circuit breaker, and caching.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            params: Query parameters
            json_body: JSON request body
            max_retries: Maximum number of retries
            use_cache: Whether to use response cache (issue #9)

        Returns the parsed JSON response.
        """
        # Check cache for GET requests (issue #9)
        cache_key = None
        if use_cache and method == "GET":
            import hashlib
            cache_key = hashlib.md5(
                f"v2:{self.provider_name}:{self.base_url}:{method}:{endpoint}:{sorted((params or {}).items())}".encode()
            ).hexdigest()
            cached = await self._cache.get(cache_key)
            if cached is not None:
                self._validate_response(cached)
                logger.debug("Cache hit for %s %s", method, endpoint)
                return cached

        if not self._circuit_breaker.can_call():
            raise CircuitBreakerOpenError(self.provider_name)

        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                # Enforce provider rate (requests per second) using token-bucket
                await self._wait_for_rate()
                client = await self._get_client()
                response = await client.request(
                    method,
                    endpoint,
                    params=params,
                    json=json_body,
                )

                if response.status_code == 429:
                    # Don't retry on rate-limit — the cache layer (module-level
                    # + Redis 24h TTL) prevents repeated calls. Retrying just
                    # triggers more 429s and wastes time.
                    raise RateLimitError(
                        self.provider_name,
                        retry_after=int(response.headers.get("Retry-After", "60")),
                    )

                response.raise_for_status()

                self._circuit_breaker.record_success()
                result = response.json()
                self._validate_response(result)

                # Cache successful GET responses (issue #9)
                if cache_key:
                    await self._cache.set(cache_key, result)
                    logger.info("Cached response for %s %s (key=%s)", method, endpoint, cache_key[:12])

                return result

            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code >= 500 and attempt < max_retries:
                    backoff = 2 ** attempt
                    logger.warning(
                        "Provider %s returned %d, backing off %ds (attempt %d/%d)",
                        self.provider_name,
                        exc.response.status_code,
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(backoff)
                    continue
                self._circuit_breaker.record_failure()
                raise ProviderError(
                    self.provider_name,
                    f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                    exc.response.status_code,
                ) from exc

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_error = exc
                # TLS failures can have an empty message. Preserve the
                # underlying exception so connection diagnostics stay useful.
                details = repr(exc)
                cause = exc.__cause__
                while cause is not None:
                    details += f" caused by {cause!r}"
                    cause = cause.__cause__
                if attempt < max_retries:
                    backoff = 2 ** attempt
                    logger.warning(
                        "Provider %s connection error, backing off %ds (attempt %d/%d): %s",
                        self.provider_name,
                        backoff,
                        attempt + 1,
                        max_retries,
                        details,
                    )
                    # Reset the client on connection errors so a corrupted
                    # connection pool doesn't poison all retries.
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = None
                    await asyncio.sleep(backoff)
                    continue
                self._circuit_breaker.record_failure()
                raise ProviderError(
                    self.provider_name,
                    f"Connection error contacting {self.base_url}: {details}",
                ) from exc

        self._circuit_breaker.record_failure()
        raise ProviderError(
            self.provider_name,
            f"Max retries exceeded: {last_error}",
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        # Closing a client must preserve cached data shared by other workers.

    def _normalize_timestamp(self, value: Any) -> datetime | None:
      """Normalize common timestamp formats into a timezone-aware UTC datetime.

      Handles:
      - epoch seconds (int/float)
      - epoch milliseconds (int/float > 1e12)
      - ISO 8601 strings with or without timezone
      - ISO 8601 strings with trailing Z
      - numeric strings representing epoch

      Naive ISO datetimes/date-only strings are explicitly interpreted as UTC.
      All timezone-aware values are converted to UTC.

      Returns:
          A timezone-aware UTC datetime, or None for unrecognized values.
      """
      if value is None:
          return None

      try:
          # Numeric types: seconds or milliseconds
          if isinstance(value, (int, float)):
              v = float(value)

              if v > 1e12:
                  v /= 1000.0

              return datetime.fromtimestamp(v, tz=timezone.utc)

          # Strings: ISO 8601 first, then numeric epoch
          if isinstance(value, str):
              s = value.strip()

              if not s:
                  return None

              # ISO 8601 with trailing Z
              if s.endswith("Z"):
                  s = s[:-1] + "+00:00"

              try:
                  parsed = datetime.fromisoformat(s)

                  # Bare dates / naive datetimes have no timezone.
                  # Provider dates such as "2026-08-17" represent the
                  # UTC calendar day, so explicitly attach UTC.
                  if parsed.tzinfo is None:
                      parsed = parsed.replace(tzinfo=timezone.utc)
                  else:
                      # Normalize any supplied offset to UTC.
                      parsed = parsed.astimezone(timezone.utc)

                  return parsed

              except ValueError:
                  # Numeric string representing epoch seconds/milliseconds
                  if s.isdigit():
                      v = int(s)

                      if v > 1e12:
                          v /= 1000.0

                      return datetime.fromtimestamp(v, tz=timezone.utc)

      except (ValueError, TypeError, OverflowError, OSError):
          logger.warning(
              "Unable to normalize timestamp value: %r",
              value,
          )

      return None

    async def _wait_for_rate(self) -> None:
        """Simple async token-bucket rate limiter enforcing `rate_limit_per_sec`.

        This is a lightweight replacement for semaphore-based concurrency limiting
        and ensures we don't exceed the configured requests-per-second.
        """
        loop = asyncio.get_running_loop()
        now = loop.time()

        if self._rb_tokens is None or self._rb_last is None:
            # Initialize bucket full
            self._rb_tokens = float(self.rate_limit_per_sec)
            self._rb_last = now

        # Refill tokens based on elapsed time
        elapsed = now - self._rb_last
        refill = elapsed * float(self.rate_limit_per_sec)
        self._rb_tokens = min(float(self.rate_limit_per_sec), self._rb_tokens + refill)
        self._rb_last = now

        if self._rb_tokens >= 1.0:
            self._rb_tokens -= 1.0
            return

        # Calculate wait time until next token is available
        needed = 1.0 - self._rb_tokens
        wait = needed / float(self.rate_limit_per_sec)
        await asyncio.sleep(wait)
        # After waiting, consume token
        self._rb_last = loop.time()
        self._rb_tokens = max(0.0, (self._rb_tokens + (self._rb_last - now) * float(self.rate_limit_per_sec)) - 1.0)


# ── Abstract provider interfaces (Section 6) ─────────────────────


class MarketDataProvider(BaseProvider):
    """Abstract interface for market-data providers (Section 6)."""

    @abstractmethod
    async def get_quote(self, ticker: str) -> dict[str, Any]:
        """Get the latest quote for a ticker."""
        ...

    @abstractmethod
    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        """Get historical OHLCV prices."""
        ...

    @abstractmethod
    async def get_market_movers(self) -> dict[str, list[dict[str, Any]]]:
        """Get top gainers and losers."""
        ...


class FundamentalDataProvider(BaseProvider):
    """Abstract interface for fundamental-data providers (Section 6)."""

    @abstractmethod
    async def get_income_statement(self, ticker: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_balance_sheet(self, ticker: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_cash_flow(self, ticker: str) -> list[dict[str, Any]]:
        ...


class NewsProvider(BaseProvider):
    """Abstract interface for news providers (Section 6)."""

    @abstractmethod
    async def search_news(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_company_news(self, ticker: str, limit: int = 50) -> list[dict[str, Any]]:
        ...


class MacroDataProvider(BaseProvider):
    """Abstract interface for macroeconomic-data providers."""

    @abstractmethod
    async def get_indicator(self, indicator_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_indicator_series(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        ...


class AlternativeDataProvider(BaseProvider):
    """Abstract interface for alternative data (insider, institutional, etc.)."""

    @abstractmethod
    async def get_insider_transactions(self, ticker: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_institutional_ownership(self, ticker: str) -> list[dict[str, Any]]:
        ...
