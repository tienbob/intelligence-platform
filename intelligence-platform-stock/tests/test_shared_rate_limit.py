from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException, Request
from redis.exceptions import ConnectionError
from app.core import rate_limit as rl


@pytest.mark.asyncio
async def test_redis_quota_and_retry(monkeypatch):
    monkeypatch.setattr(rl.settings, 'RATE_LIMIT_ENABLED', True)
    limiter = rl.RedisRateLimiter('redis://unused')
    limiter.client = AsyncMock()
    limiter.client.eval.side_effect = [0, 23]
    await limiter.check('user:42:analysis', 1)
    with pytest.raises(HTTPException) as error:
        await limiter.check('user:42:analysis', 1)
    assert error.value.status_code == 429
    assert error.value.headers['Retry-After'] == '23'
    calls = limiter.client.eval.call_args_list
    assert calls[0].args[2] == calls[1].args[2]
    assert calls[0].args[-1] != calls[1].args[-1]


@pytest.mark.asyncio
async def test_redis_outage_does_not_bypass_budget(monkeypatch):
    monkeypatch.setattr(rl.settings, 'RATE_LIMIT_ENABLED', True)
    limiter = rl.RedisRateLimiter('redis://unused')
    limiter.client = AsyncMock()
    limiter.client.eval.side_effect = ConnectionError('offline')
    with pytest.raises(HTTPException) as error:
        await limiter.check('user:42:analysis')
    assert error.value.status_code == 503


def test_spoofed_identity_headers_do_not_change_client(monkeypatch):
    monkeypatch.setattr(rl.settings, 'INTERNAL_SERVICE_KEY', 'real-key')
    request = Request({'type': 'http', 'headers': [(b'x-user-id', b'42'),
        (b'x-service-key', b'wrong'), (b'x-forwarded-for', b'1.2.3.4')], 'client': ('10.0.0.2', 12)})
    assert rl.get_client_key(request) == '10.0.0.2'


@pytest.mark.asyncio
async def test_production_requires_shared_storage(monkeypatch):
    monkeypatch.setattr(rl.settings, 'REDIS_URL', None)
    monkeypatch.setattr(rl.settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(rl.settings, 'RATE_LIMIT_ENABLED', True)
    with pytest.raises(HTTPException) as error:
        await rl.rate_limit(Request({'type': 'http'}))
    assert error.value.status_code == 503
