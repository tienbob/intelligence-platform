import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from app.domains.stock.context_builder import StockContextBuilder
from app.shared.entities import EntityRef, Observation

REF = EntityRef('stock', 'company', 'AAPL')
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def observation(kind, data, source='finnhub', when=NOW):
    return Observation(REF, when, data=data, source=source, kind=kind)


def test_market_and_news_use_kind_and_dates_not_provider_or_input_order():
    items = [
        observation('news', {'title': 'Recent news', 'published_at': '2026-10-09'}),
        observation('price', {'close': 12, 'high': 13, 'low': 11, 'volume': 200, 'timestamp': '2026-10-08'}),
        observation('price', {'close': 10, 'high': 11, 'low': 9, 'volume': 100, 'timestamp': '2026-10-07'}),
        observation('news', {'title': 'Older news', 'published_at': '2026-10-07'}),
    ]
    context = asyncio.run(StockContextBuilder().build(REF, [], items, {}))
    market = context.domain_snapshots['market_snapshot']
    assert market['latest_price'] == 12
    assert market['price_change_1d'] == pytest.approx(0.2)
    assert market['avg_volume_30d'] == 150
    assert market['price_high_30d'] == 13
    assert context.domain_snapshots['news_snapshot']['recent_news'][0]['title'] == 'Recent news'


def test_missing_data_is_empty_and_reported_instead_of_placeholder_values():
    context = asyncio.run(StockContextBuilder().build(REF, [], [], {}))
    for name in ('market', 'technical', 'fundamental', 'risk'):
        assert context.domain_snapshots[f'{name}_snapshot'] == {}
        assert f'{name}_snapshot' in context.metadata['missing_snapshots']


def test_context_rejects_observations_for_another_company():
    item = Observation(EntityRef('stock', 'company', 'MSFT'), NOW, kind='quote', data={'price': 100})
    with pytest.raises(ValueError, match='another entity'):
        asyncio.run(StockContextBuilder().build(REF, [], [item], {}))


def test_empty_nested_fundamentals_is_reported_missing():
    items = [observation('fundamental_snapshot', {'metrics': {}, 'latest_statement': {}})]
    context = asyncio.run(StockContextBuilder().build(REF, [], items, {}))
    assert 'fundamental_snapshot' in context.metadata['missing_snapshots']


def test_latest_typed_snapshots_override_old_snapshots_without_source_guessing():
    items = [observation('technical_snapshot', {'rsi_14': 70}),
             observation('technical_snapshot', {'rsi_14': 40}, when=datetime(2026, 10, 1, tzinfo=timezone.utc)),
             observation('risk_metric', {'risk_score': 25}),
             observation('event', {'type': 'earnings', 'date': '2026-10-08'})]
    context = asyncio.run(StockContextBuilder().build(REF, [], items, {}))
    assert context.domain_snapshots['technical_snapshot']['rsi_14'] == 70
    assert context.domain_snapshots['risk_snapshot']['risk_score'] == 25
    assert context.domain_snapshots['event_snapshot']['event_count'] == 1


def test_missing_persisted_company_fails_instead_of_analyzing_empty_context(monkeypatch):
    from app.domains.stock.providers import persisted
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    resolver = AsyncMock()
    resolver.resolve.return_value = None
    monkeypatch.setattr(persisted, 'EntityResolver', lambda session: resolver)
    provider = persisted.PersistedStockProvider(session_factory=Session)
    with pytest.raises(LookupError, match='No persisted company'):
        asyncio.run(provider.fetch(REF))


def test_factory_enforces_stock_validation_for_injected_llm():
    from app.domains.stock.pipeline_factory import StockValidationAdapter
    from app.domains.stock.scoring.analysis_validator import AnalysisValidationError
    with pytest.raises(AnalysisValidationError):
        asyncio.run(StockValidationAdapter().validate({'summary': 'Missing investment fields'}))


def test_rag_adapter_filters_to_resolved_company(monkeypatch):
    from types import SimpleNamespace
    from app.core import database
    from app.domains.stock.normalization import companies
    from app.domains.stock.scoring import rag
    from app.domains.stock.pipeline_factory import StockRAGPipelineAdapter
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    resolver = AsyncMock()
    resolver.resolve.return_value = SimpleNamespace(id=7, ticker='AAPL', name='Apple Inc.')
    retriever = AsyncMock()
    retriever.retrieve_context.return_value = {'news': []}
    monkeypatch.setattr(database, 'async_session_factory', Session)
    monkeypatch.setattr(companies, 'EntityResolver', lambda session: resolver)
    monkeypatch.setattr(rag, 'RAGService', lambda session, **kwargs: retriever)
    result = asyncio.run(StockRAGPipelineAdapter().retrieve_context('arbitrary query', entity_id='AAPL'))
    assert result == {'news': []}
    retriever.retrieve_context.assert_awaited_once_with('Analysis of AAPL Apple Inc.', company_id=7)
