import asyncio
from unittest.mock import AsyncMock
import pytest
from app.domains.stock.api import market


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(market, '_indices_lock', asyncio.Lock())
    monkeypatch.setattr(market, '_indices_cache', {})
    monkeypatch.setattr(market, '_indices_cache_at', 0)
    monkeypatch.setattr(market, '_indices_last_good', None)
    monkeypatch.setattr(market, '_indices_retry_after', 0)
    client = AsyncMock()
    client.get_quote.return_value = {'price': 100, 'change': 1, 'change_percent': 1}
    monkeypatch.setattr(market, 'FMPProvider', lambda: client)
    return client


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_refresh(provider):
    results = await asyncio.gather(*(market.get_market_indices_data() for _ in range(12)))
    assert provider.get_quote.await_count == 4
    assert all(result == results[0] for result in results)
    assert results[0]['stale'] is False
    for call in provider.get_quote.call_args_list:
        assert call.kwargs['use_cache'] is False
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_outage_preserves_last_good_and_throttles_retries(provider, monkeypatch):
    good = await market.get_market_indices_data()
    monkeypatch.setattr(market, '_indices_cache_at', -1000)
    provider.get_quote.side_effect = RuntimeError('offline')
    stale = await market.get_market_indices_data()
    assert stale['indices'] == good['indices']
    assert stale['fetched_at'] == good['fetched_at']
    assert stale['stale'] is True
    await market.get_market_indices_data()
    assert provider.get_quote.await_count == 8
    assert good['stale'] is False


@pytest.mark.asyncio
async def test_empty_provider_quotes_are_not_cached_as_real_prices(provider):
    provider.get_quote.return_value = {'price': 0}
    result = await market.get_market_indices_data()
    assert result['indices'] == []
    assert result['stale'] is True
    assert market._indices_cache == {}
    provider.close.assert_awaited_once()
