"""Optional sources must be absent from queries, prompt input and degraded status."""
import asyncio
import itertools
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.domains.stock.manifest import StockDomain
from app.domains.stock.pipeline_factory import build_stock_pipeline
from app.domains.stock.providers import persisted
from app.shared.entities import AnalysisRequest, EntityRef


@pytest.mark.parametrize('flags', list(itertools.product((False, True), repeat=2)))
@pytest.mark.asyncio
async def test_production_rag_skips_disabled_searches(monkeypatch, flags):
    from app.core import database
    from app.domains.stock.pipeline_factory import StockRAGPipelineAdapter
    from app.domains.stock.scoring import rag
    from app.domains.stock.normalization import companies
    include_news, include_fundamentals = flags
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(database, 'async_session_factory', Session)
    monkeypatch.setattr(companies, 'EntityResolver', lambda session: SimpleNamespace(
        resolve=AsyncMock(return_value=SimpleNamespace(id=7, ticker='AAPL', name='Apple'))))
    searches = {name: AsyncMock(return_value=[]) for name in
                ('hybrid_search', 'retrieve_filings', 'retrieve_events', 'retrieve_similar_analyses')}
    for name, search in searches.items():
        monkeypatch.setattr(rag.RAGService, name, search)
    request = AnalysisRequest(EntityRef('stock', 'company', 'AAPL'), parameters={
        'include_news': include_news, 'include_fundamentals': include_fundamentals})
    await StockRAGPipelineAdapter(embedding_service=object()).retrieve_context_for_analysis('AAPL', request)
    assert searches['hybrid_search'].await_count == int(include_news)
    assert searches['retrieve_events'].await_count == int(include_news)
    assert searches['retrieve_filings'].await_count == int(include_fundamentals)
    assert searches['retrieve_similar_analyses'].await_count == 1


@pytest.mark.parametrize('flags', list(itertools.product((False, True), repeat=4)))
def test_all_inclusion_combinations_flow_through_framework(monkeypatch, flags):
    options = dict(zip(('include_news','include_fundamentals','include_technical','include_macro'), flags))
    calls, prompts = [], []
    company = SimpleNamespace(ticker='AAPL', id=7, name='Apple', sector='Technology', industry='Tech', market_cap=100)
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=company))
    monkeypatch.setattr(persisted, 'EntityResolver', lambda session: resolver)
    class Reader:
        def __init__(self, session): self.macro_engine = self
        async def get_macro_snapshot(self):
            calls.append('macro_snapshot');return {'indicator':10}
        def __getattr__(self, name):
            section = name.removeprefix('build_')
            async def read(company_id):
                calls.append(section)
                if section == 'fundamental_snapshot': return {'metrics': {'net_margin': .1}, 'latest_statement': {}}
                return {'value': 1}
            return read
    provider = persisted.PersistedStockProvider(session_factory=Session, reader_factory=Reader)
    class Scorer:
        async def score(self, *args): return {'score':50,'confidence':.8,'recommendation':'NEUTRAL','metadata':{'score_id':1}}
    class Domain(StockDomain):
        def get_ingestion_providers(self): return {'persisted':provider}
        def get_scoring_strategy(self): return Scorer()
    class Registry:
        def get(self, name): return Domain()
    class Rag:
        async def retrieve_context_for_analysis(self, query, request):
            assert request.parameters == options
            return await self.retrieve_context(query)
        async def retrieve_context(self, *args, **kw):
            return {kind:[{'id':1,'content':kind+' evidence'}] for kind in ('news','events','filings')}
    class LLM:
        async def analyze(self, context, **kwargs):
            prompts.append(context)
            return dict(summary='s',market_interpretation='m',causes=[],bull_case=[],bear_case=[],investment_thesis='t',confidence=.8)
    pipe = build_stock_pipeline(registry=Registry(), rag_service=Rag(), llm_service=LLM())
    result = asyncio.run(pipe.run(AnalysisRequest(EntityRef('stock','company','AAPL'), analysis_type='company',parameters=options)))
    assert result.status == 'completed', result.summary
    excluded = Domain.excluded_sections(options)
    assert not excluded.intersection(calls)
    assert not excluded.intersection(prompts[0])
    assert not excluded.intersection(result.metadata['domain_snapshots'])
    assert result.metadata['stages']['context'] == 'success'
    if not options['include_news']: assert not {'news','events'}.intersection(prompts[0]['rag_context'])
    if not options['include_fundamentals']: assert 'filings' not in prompts[0]['rag_context']
