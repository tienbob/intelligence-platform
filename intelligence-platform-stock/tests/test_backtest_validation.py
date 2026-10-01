import pytest
from pydantic import ValidationError
from app.domains.stock.schemas.backtest import BacktestRunRequest


def request(**overrides):
    return BacktestRunRequest.model_validate({
        'name': 'Example', 'start_date': '2025-01-01T00:00:00Z',
        'end_date': '2025-06-01T00:00:00Z', **overrides,
    })


@pytest.mark.parametrize('overrides', [
    {'parameters': {'rebalance_days': 0}},
    {'parameters': {'rebalance_days': -1}},
    {'parameters': {'rebalance_days': 1.5}},
    {'parameters': {'rebalance_days': True}},
    {'parameters': {'threshold': 101}},
    {'parameters': {'unknown_setting': 1}},
    {'strategy': 'momentum', 'parameters': {'top_n': 0}},
    {'strategy': 'momentum', 'parameters': {'lookback_trading_days': -10}},
    {'strategy': 'portfolio_optimizer', 'parameters': {'max_position_weight': 2}},
    {'strategy': 'portfolio_optimizer', 'parameters': {'risk_profile': 'invalid'}},
    {'strategy': 'portfolio_optimizer', 'parameters': {'volatility_lookback': 0}},
    {'strategy': 'equal_weight', 'parameters': {'threshold': 70}},
    {'initial_capital': float('inf')}, {'initial_capital': float('nan')},
    {'name': ' '}, {'name': 'x' * 201}, {'tickers': []}, {'tickers': ['']},
    {'snapshot_id': 0}, {'benchmark_ticker': 'x' * 21},
    {'end_date': '2025-06-01T00:00:00'},
])
def test_invalid_requests_rejected_before_queueing(overrides):
    with pytest.raises(ValidationError):
        request(**overrides)


@pytest.mark.parametrize('strategy', ['score_threshold', 'momentum', 'equal_weight', 'portfolio_optimizer'])
def test_defaults_remain_compatible(strategy):
    assert request(strategy=strategy).parameters == {}


def test_valid_values_and_zero_threshold_preserved():
    result = request(name=' Example ', tickers=[' aapl '], parameters={'threshold': 0, 'rebalance_days': 1})
    assert result.name == 'Example'
    assert result.tickers == ['AAPL']
    assert result.parameters == {'threshold': 0, 'rebalance_days': 1}


@pytest.mark.asyncio
async def test_database_failure_rolls_back_before_persisting_failed_run(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.domains.stock.scoring import backtest

    events = []
    row = SimpleNamespace(id=42, status='queued', error_message=None)

    async def rollback():
        events.append('rollback')

    async def get(model, row_id):
        assert events == ['rollback']
        assert row_id == 42
        events.append('reload')
        return row

    async def commit(session):
        assert row.status == 'failed'
        events.append('commit')

    session = SimpleNamespace(flush=AsyncMock(), rollback=rollback, get=get)
    engine = backtest.BacktestEngine(session)
    monkeypatch.setattr(engine, '_load_price_data', AsyncMock(side_effect=RuntimeError('database failure')))
    monkeypatch.setattr(backtest, 'commit_session', commit)
    data = request(strategy='equal_weight')
    with pytest.raises(RuntimeError, match='database failure'):
        await engine.run_backtest(**data.model_dump(), existing_run=row)
    assert events == ['rollback', 'reload', 'commit']
    assert row.error_message == 'database failure'
