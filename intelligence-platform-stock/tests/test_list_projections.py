"""Compile actual list queries and ensure heavy payloads stay out of SELECT."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.requests import Request
from sqlalchemy.dialects import postgresql
from app.domains.stock.scoring.backtest import BacktestEngine
from app.domains.stock.api.analysis import list_analysis_jobs


def session():
    result = MagicMock()
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    return AsyncMock(execute=AsyncMock(return_value=result))


def selected_sql(db):
    query = db.execute.call_args_list[0].args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    return sql.split('FROM', 1)[0], sql


@pytest.mark.asyncio
async def test_analysis_poll_does_not_fetch_llm_payload():
    db = session()
    request = Request({'type': 'http', 'headers': [], 'state': {'actor': {'user_id': 42, 'role': 'USER'}}})
    await list_analysis_jobs(request, limit=20, offset=0, db=db)
    projection, sql = selected_sql(db)
    assert 'llm_analysis' not in projection
    assert 'analyses.analysis_id' in projection
    assert 'analyses.id DESC' in sql


@pytest.mark.asyncio
async def test_backtest_list_does_not_fetch_parameters():
    db = session()
    await BacktestEngine(db).list_runs(actor={'user_id': 42, 'role': 'USER'})
    projection, sql = selected_sql(db)
    assert 'parameters' not in projection
    assert 'snapshot_coverage' in projection
    assert 'backtest_runs.id DESC' in sql


@pytest.mark.asyncio
async def test_snapshot_list_fetches_metadata_only():
    db = session()
    await BacktestEngine(db).list_snapshots()
    projection, sql = selected_sql(db)
    for field in ('prices', 'scores', 'fundamentals', 'events', 'news'):
        assert f'backtest_snapshots.{field}' not in projection
    assert 'description' in projection
    assert 'backtest_snapshots.id DESC' in sql
