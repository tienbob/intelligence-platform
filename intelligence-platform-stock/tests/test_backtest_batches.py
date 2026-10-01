from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.dialects import postgresql
from app.domains.stock.scoring import backtest

DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def result(rows):
    response = MagicMock()
    response.scalars.return_value.all.return_value = rows
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize('count, expected', [(0, 0), (20, 1), (501, 2)])
async def test_price_query_count_scales_by_batch(count, expected):
    db = AsyncMock()
    db.execute.return_value = result([])
    assert await backtest.BacktestEngine(db)._prices_by_company(list(range(count)), DATE, DATE) == {}
    assert db.execute.await_count == expected
    for call in db.execute.call_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect()))
        assert 'timestamp >=' in sql and 'timestamp <=' in sql
        assert 'stock_prices.interval =' in sql


@pytest.mark.asyncio
async def test_snapshot_batches_preserve_payload_and_as_of_filter(monkeypatch):
    companies = [SimpleNamespace(id=1, ticker='AAA'), SimpleNamespace(id=2, ticker='BBB')]
    prices = [SimpleNamespace(company_id=1, timestamp=DATE, close=10, volume=20)]
    scores = [SimpleNamespace(company_id=2, timestamp=DATE, overall_score=0,
                              recommendation='HOLD', scoring_model='test', scoring_version='1')]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[result(companies), result(prices), result(scores)])
    monkeypatch.setattr(backtest, 'commit_session', AsyncMock())
    snapshot = await backtest.BacktestEngine(db).create_snapshot('Example', DATE)
    assert db.execute.await_count == 3
    assert snapshot.prices == {'AAA': [{'timestamp': DATE.isoformat(), 'close': 10, 'volume': 20}]}
    assert snapshot.scores['BBB']['overall_score'] == 0
    score_sql = str(db.execute.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert 'DISTINCT ON' in score_sql and 'timestamp <=' in score_sql
    assert 'id DESC' in score_sql
