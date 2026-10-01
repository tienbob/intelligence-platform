from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.dialects import postgresql
from app.domains.stock.api.portfolio import _build_opportunities
from app.domains.stock.scoring.risk import RiskEngine


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [1, 20])
async def test_risks_use_two_queries_independent_of_company_count(count):
    scores = MagicMock()
    scores.all.return_value = [(SimpleNamespace(overall_score=0),
        SimpleNamespace(id=i, ticker=f'T{i}', sector='Technology')) for i in range(count)]
    risks = MagicMock()
    risks.scalars.return_value.all.return_value = [
        SimpleNamespace(company_id=i, risk_score=0, volatility=0) for i in range(count)]
    db = AsyncMock()
    db.execute.side_effect = [scores, risks]
    result = await _build_opportunities(db)
    assert db.execute.await_count == 2
    assert len(result) == count
    assert all(row['score'] == row['risk_score'] == row['volatility'] == 0 for row in result)
    sql = str(db.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert 'DISTINCT ON' in sql
    assert 'timestamp DESC' in sql and 'id DESC' in sql


@pytest.mark.asyncio
async def test_empty_risk_batch_does_not_query():
    db = AsyncMock()
    assert await RiskEngine(db).get_latest_risks([]) == {}
    db.execute.assert_not_awaited()
