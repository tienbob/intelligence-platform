import asyncio, copy, json, logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy import select, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)
from app.core.database import async_session_factory
from app.domains.stock.models.company import Company
from app.domains.stock.models.analysis import InvestmentScore
from app.domains.stock.manifest import StockDomain
from app.domains.stock.providers.persisted import PersistedStockProvider
from app.domains.stock.snapshots import StockSnapshotReader
from app.domains.stock.pipeline_factory import build_stock_pipeline
from app.shared.entities import AnalysisRequest, EntityRef

@asynccontextmanager
async def read_only():
    async with async_session_factory() as session:
        await session.execute(text('SET TRANSACTION READ ONLY'))
        yield session
        await session.rollback()

class Rag:
    async def retrieve_context(self, *args, **kwargs):
        return {'news': [], 'filings': [], 'events': [], 'previous_analyses': []}

class Score:
    async def score(self, ref, context, llm_output):
        async with read_only() as session:
            company = (await session.execute(select(Company).where(Company.ticker == ref.entity_id))).scalar_one()
            row = (await session.execute(select(InvestmentScore).where(InvestmentScore.company_id == company.id).order_by(InvestmentScore.timestamp.desc()).limit(1))).scalar_one()
            return {'score': row.overall_score, 'confidence': row.confidence, 'recommendation': row.recommendation, 'metadata': {'score_id': row.id}}

class Domain(StockDomain):
    def get_ingestion_providers(self):
        return {'stock_database': PersistedStockProvider(session_factory=read_only)}
    def get_scoring_strategy(self): return Score()

class Registry:
    def get(self, name): return Domain() if name == 'stock' else None

class RecordedLLM:
    def __init__(self, expected): self.expected = expected
    async def analyze(self, context, **kwargs):
        for key, value in self.expected.items():
            assert context[key] == value, f'{key}: reader/framework mismatch'
        fixture = json.loads(Path('tests/golden/fixtures/aapl_pipeline.json').read_text())
        response = copy.deepcopy(fixture['llm_response'])
        response['_meta'] = {'model': 'recorded-fixture', 'provider': 'fixture', 'tokens_used': 0, 'prompt_version': '1.0'}
        return response

async def main():
    async with read_only() as session:
        companies = (await session.execute(select(Company).order_by(Company.id))).scalars().all()
        identities = [(c.id, c.ticker) for c in companies]
    results = []
    for company_id, ticker in identities:
        async with read_only() as session:
            company = await session.get(Company, company_id)
            reader = StockSnapshotReader(session)
            expected = {'company': {key:getattr(company,key,None) for key in ('ticker','name','sector','industry','market_cap')}}
            for section in ('market','technical','fundamental','news','event','risk','anomaly'):
                expected[f'{section}_snapshot'] = await getattr(reader,f'build_{section}_snapshot')(company.id)
            expected['macro_snapshot'] = await reader.macro_engine.get_macro_snapshot()
        pipeline = build_stock_pipeline(registry=Registry(), rag_service=Rag(), llm_service=RecordedLLM(expected))
        result = await pipeline.run(AnalysisRequest(EntityRef('stock', 'company', ticker), analysis_type='company'))
        assert result.status == 'completed', result.summary
        results.append({'ticker': ticker, 'snapshots_match': True, 'observations': len(result.evidence), 'context_status': result.metadata['stages']['context']})
    print(json.dumps(results))
asyncio.run(main())
