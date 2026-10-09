"""Twelve Data Basic adapter: quotes and split-adjusted OHLCV.

Quota reservations are shared through Redis across API/worker processes.
Without Redis, a conservative process-local budget is used.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.domains.stock.config import get_stock_config
from app.domains.stock.providers.base import MarketDataProvider, ProviderError, RateLimitError

config = get_stock_config()


class TwelveDataProvider(MarketDataProvider):
    provider_name = "twelve_data"
    base_url = config.TWELVE_DATA_BASE_URL
    _budgets: dict[str, tuple[int, int, int, int]] = {}
    # Atomic: never consume a minute credit if the daily budget is exhausted.
    _reserve = """
    local minute = tonumber(redis.call('GET', KEYS[1]) or '0')
    local day = tonumber(redis.call('GET', KEYS[2]) or '0')
    if minute >= tonumber(ARGV[1]) or day >= tonumber(ARGV[2]) then return 0 end
    redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 120)
    redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 172800)
    return 1
    """

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key or config.TWELVE_DATA_API_KEY)
        self._quota_client = None

    async def _wait_for_rate(self) -> None:
        if not self.api_key:
            raise ProviderError(self.provider_name, "TWELVE_DATA_API_KEY is required")
        now = int(time.time())
        minute, day = now // 60, now // 86400
        identity = hashlib.sha256(self.api_key.encode()).hexdigest()[:20]
        settings = get_settings()
        if settings.REDIS_CACHE_ENABLED and settings.REDIS_URL:
            try:
                if self._quota_client is None:
                    import redis.asyncio as redis
                    self._quota_client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
                accepted = await self._quota_client.eval(
                    self._reserve, 2,
                    f'twelve_data:quota:{identity}:minute:{minute}',
                    f'twelve_data:quota:{identity}:day:{day}',
                    config.TWELVE_DATA_CREDITS_PER_MINUTE,
                    config.TWELVE_DATA_CREDITS_PER_DAY,
                )
            except Exception as exc:
                raise ProviderError(self.provider_name, "Shared quota store unavailable") from exc
        else:
            old_minute, count, old_day, daily = self._budgets.get(identity, (minute, 0, day, 0))
            count = count if old_minute == minute else 0
            daily = daily if old_day == day else 0
            accepted = count < config.TWELVE_DATA_CREDITS_PER_MINUTE and daily < config.TWELVE_DATA_CREDITS_PER_DAY
            if accepted:
                self._budgets[identity] = (minute, count + 1, day, daily + 1)
        if not accepted:
            raise RateLimitError(self.provider_name, retry_after=60 - now % 60)

    async def _fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError(self.provider_name, "TWELVE_DATA_API_KEY is required")
        data = await self._request('GET', endpoint, params=self._build_params(apikey=self.api_key, **params))
        self._validate_response(data)
        return data

    def _validate_response(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise ProviderError(self.provider_name, "Unexpected API response")
        if data.get('status') == 'error':
            code = data.get('code')
            if str(code) == '429':
                raise RateLimitError(self.provider_name)
            raise ProviderError(self.provider_name, data.get('message', 'API error'), code)

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._fetch('/quote', symbol=ticker, timezone='UTC')
        if not data.get('close'):
            raise ProviderError(self.provider_name, f'No quote for {ticker}')
        return {
            'ticker': ticker, 'price': float(data['close']),
            'change': float(data.get('change') or 0),
            'change_percent': float(data.get('percent_change') or 0),
            'volume': int(float(data.get('volume') or 0)),
            'timestamp': self._normalize_timestamp(data.get('timestamp') or data.get('datetime')),
        }

    async def get_historical_prices(self, ticker: str, start_date: datetime, end_date: datetime, interval: str = '1d') -> list[dict[str, Any]]:
        intervals = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1h', '1d': '1day', '1W': '1week', '1M': '1month'}
        if interval not in intervals:
            raise ProviderError(self.provider_name, f'Unsupported interval: {interval}')
        def utc(value: datetime) -> datetime:
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        cursor, end = utc(start_date), utc(end_date)
        if cursor > end:
            raise ProviderError(self.provider_name, 'start_date must precede end_date')
        records = {}
        # Page backwards in bounded 5000-bar windows; fail rather than truncate.
        while end >= cursor:
            data = await self._fetch('/time_series', symbol=ticker, interval=intervals[interval], start_date=cursor.strftime('%Y-%m-%d %H:%M:%S'), end_date=end.strftime('%Y-%m-%d %H:%M:%S'), timezone='UTC', order='DESC', outputsize=5000, adjust='splits')
            values = data.get('values', [])
            for row in values:
                stamp = self._normalize_timestamp(row.get('datetime'))
                if stamp is None:
                    raise ProviderError(self.provider_name, 'Invalid price timestamp')
                if cursor <= stamp <= end:
                    records[stamp] = {
                        'timestamp': stamp,
                        **{field: float(row[field]) for field in ('open', 'high', 'low', 'close')},
                        'adjusted_close': float(row['close']),
                        'volume': int(float(row.get('volume') or 0)),
                    }
            if len(values) < 5000:
                break
            oldest = min(self._normalize_timestamp(r['datetime']) for r in values)
            from datetime import timedelta
            next_end = oldest - timedelta(seconds=1)
            if next_end >= end:
                raise ProviderError(self.provider_name, 'Historical pagination made no progress')
            end = next_end
        return [records[t] for t in sorted(records)]

    async def get_market_movers(self) -> dict[str, list[dict[str, Any]]]:
        raise ProviderError(self.provider_name, 'Market movers are not available on the Basic plan; use FMP')

    async def close(self) -> None:
        if self._quota_client is not None:
            await self._quota_client.aclose()
        await super().close()
