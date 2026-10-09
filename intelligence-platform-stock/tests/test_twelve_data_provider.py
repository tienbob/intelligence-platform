import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import pytest
from app.domains.stock.providers.base import ProviderError, RateLimitError
from app.domains.stock.providers.twelve_data import TwelveDataProvider


def test_history_normalization():
    async def run():
        provider = TwelveDataProvider('test')
        provider._request = AsyncMock(return_value={'values': [
            {'datetime': day, 'open': '10', 'high': '12', 'low': '9', 'close': '11', 'volume': '100'}
            for day in ('2026-10-02', '2026-10-01')]})
        rows = await provider.get_historical_prices('AAPL', datetime(2026, 10, 1), datetime(2026, 10, 3))
        assert len(rows) == 2
        assert rows[0]['timestamp'] == datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert rows[0]['close'] == 11.0
        assert provider._request.call_args.kwargs['params']['adjust'] == 'splits'
    asyncio.run(run())


def test_body_errors():
    async def run():
        provider = TwelveDataProvider('test')
        provider._request = AsyncMock(return_value={'status': 'error', 'code': 429})
        with pytest.raises(RateLimitError):
            await provider.get_quote('AAPL')
        provider._request.return_value = {'status': 'error', 'code': 403, 'message': 'subscription'}
        with pytest.raises(ProviderError, match='subscription'):
            await provider.get_quote('AAPL')
    asyncio.run(run())


def test_shared_local_quota():
    async def run():
        with patch('app.domains.stock.providers.twelve_data.get_settings', return_value=SimpleNamespace(REDIS_CACHE_ENABLED=False)):
            TwelveDataProvider._budgets.clear()
            with patch('app.domains.stock.providers.twelve_data.time.time', return_value=120):
                for _ in range(8):
                    await TwelveDataProvider('quota-test')._wait_for_rate()
                with pytest.raises(RateLimitError):
                    await TwelveDataProvider('quota-test')._wait_for_rate()
    asyncio.run(run())


def test_routing_excludes_massive():
    from app.domains.stock.providers.factory import DEFAULT_PROVIDER_CHAINS, METHOD_FALLBACK_CHAINS
    for chain in list(DEFAULT_PROVIDER_CHAINS.values()) + list(METHOD_FALLBACK_CHAINS.values()):
        assert all(cls.provider_name != 'massive' for cls in chain)


def test_finnhub_company_news():
    from app.domains.stock.providers.finnhub import FinnhubProvider
    async def run():
        provider = FinnhubProvider('test')
        provider._request = AsyncMock(return_value=[{'id': 1, 'headline': 'Hello', 'related': 'AAPL, MSFT'}])
        rows = await provider.get_company_news('AAPL')
        params = provider._request.call_args.kwargs['params']
        assert params['from'] < params['to']
        assert rows[0]['tickers'] == ['AAPL', 'MSFT']
    asyncio.run(run())


def test_sec_normalization_omits_ytd_and_preserves_annual_and_quarterly():
    from app.domains.stock.providers.sec import SECProvider
    def point(start, end, value):
        return {'start': start, 'end': end, 'val': value, 'form': '10-K', 'filed': '2026-02-01'}
    rows = SECProvider.normalize_statements({'facts': {'us-gaap': {
        'Revenues': {'units': {'USD': [point('2025-01-01', '2025-12-31', 100), point('2025-10-01', '2025-12-31', 30), point('2025-01-01', '2025-06-30', 50)]}},
        'Assets': {'units': {'USD': [{'end': '2025-12-31', 'val': 200, 'form': '10-K', 'filed': '2026-02-01'}]}},
        'NetCashProvidedByUsedInOperatingActivities': {'units': {'USD': [point('2025-01-01', '2025-12-31', 40)]}},
        'PaymentsToAcquirePropertyPlantAndEquipment': {'units': {'USD': [point('2025-01-01', '2025-12-31', 10)]}},
    }}})
    assert len(rows) == 2
    annual = next(r for r in rows if r['period_type'] == 'annual')
    assert annual['revenue'] == 100
    assert annual['free_cash_flow'] == 30
    assert all(r['total_assets'] == 200 for r in rows)


def test_redis_quota_is_reserved_atomically_and_failure_is_closed():
    async def run():
        with patch('app.domains.stock.providers.twelve_data.get_settings', return_value=SimpleNamespace(REDIS_CACHE_ENABLED=True, REDIS_URL='redis://unused')):
            provider = TwelveDataProvider('redis-test')
            provider._quota_client = AsyncMock()
            provider._quota_client.eval.return_value = 1
            await provider._wait_for_rate()
            assert provider._quota_client.eval.call_args.args[1] == 2
            provider._quota_client.eval.return_value = 0
            with pytest.raises(RateLimitError):
                await provider._wait_for_rate()
            provider._quota_client.eval.side_effect = OSError('offline')
            with pytest.raises(ProviderError, match='quota store unavailable'):
                await provider._wait_for_rate()
    asyncio.run(run())


def test_history_pages_without_losing_old_bars():
    from datetime import timedelta
    async def run():
        provider = TwelveDataProvider('test')
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        def row(index):
            return {'datetime': (start + timedelta(minutes=index)).isoformat(), 'open': '10', 'high': '12', 'low': '9', 'close': '11'}
        provider._request = AsyncMock(side_effect=[{'values': [row(i) for i in range(5001, 1, -1)]}, {'values': [row(1), row(0)]}])
        rows = await provider.get_historical_prices('AAPL', start, start + timedelta(minutes=5002), '1m')
        assert len(rows) == 5002
        assert rows[0]['timestamp'] == start
        assert provider._request.await_count == 2
    asyncio.run(run())


def test_http_200_quota_error_does_not_poison_cache():
    import httpx
    async def run():
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={'status': 'error', 'code': 429} if len(calls) == 1 else {'close': '12'})
        provider = TwelveDataProvider('fake-audit-key')
        provider._client = httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(respond))
        provider._wait_for_rate = AsyncMock()
        with pytest.raises(RateLimitError):
            await provider.get_quote('AAPL')
        assert (await provider.get_quote('AAPL'))['price'] == 12
        assert (await provider.get_quote('AAPL'))['price'] == 12
        assert len(calls) == 2
        await provider.close()
    asyncio.run(run())


def test_scheduled_daily_history_bounds_reuse_cache():
    from app.domains.stock.ingestion.market import MarketDataIngestion
    from datetime import timedelta
    class Clock(datetime):
        current = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls.current
    async def run():
        ingestion = MarketDataIngestion(AsyncMock())
        ingestion.ingest_historical_prices = AsyncMock(return_value=5)
        with patch('app.domains.stock.ingestion.market.datetime', Clock):
            await ingestion.ingest_recent_prices('AAPL', days=5)
            first = ingestion.ingest_historical_prices.call_args
            Clock.current += timedelta(minutes=5)
            await ingestion.ingest_recent_prices('AAPL', days=5)
            assert ingestion.ingest_historical_prices.call_args == first
            assert first.args[2] == datetime(2026, 10, 8, 23, 59, 59, tzinfo=timezone.utc)
            Clock.current += timedelta(days=1)
            await ingestion.ingest_recent_prices('AAPL', days=5)
            assert ingestion.ingest_historical_prices.call_args != first
    asyncio.run(run())


def test_statement_uniqueness_includes_period_type():
    from app.domains.stock.models.financial import FinancialStatement
    from sqlalchemy import UniqueConstraint
    constraints = [c for c in FinancialStatement.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any([c.name for c in constraint.columns] == ['company_id', 'period', 'period_type'] for constraint in constraints)
    assert not any(index.unique and [c.name for c in index.columns] == ['company_id', 'period'] for index in FinancialStatement.__table__.indexes)


def test_closing_provider_preserves_shared_cache():
    async def run():
        provider = TwelveDataProvider('close-test')
        provider._cache.clear = AsyncMock()
        await provider.close()
        provider._cache.clear.assert_not_awaited()
    asyncio.run(run())
