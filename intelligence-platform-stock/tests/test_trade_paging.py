from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.dialects import postgresql
from app.domains.stock.scoring.backtest import BacktestEngine


@pytest.mark.asyncio
async def test_trade_page_uses_offset_and_stable_order():
    response = MagicMock()
    response.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = response
    assert await BacktestEngine(db).get_trades(42, limit=101, offset=100) == []
    query = db.execute.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'LIMIT 101 OFFSET 100' in sql
    assert 'backtest_trades.trade_date, backtest_trades.id' in sql
    assert 'backtest_trades.run_id = 42' in sql


@pytest.mark.asyncio
@pytest.mark.parametrize('count, more', [(0, False), (2, False), (3, True)])
async def test_trade_endpoint_uses_lookahead_without_returning_extra_row(monkeypatch, count, more):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.domains.stock.api import backtest as api

    rows = [SimpleNamespace(id=i, ticker='AAA', action='BUY', trade_date=datetime.now(timezone.utc),
                            price=10, shares=1, amount=10) for i in range(count)]
    engine = SimpleNamespace(get_run=AsyncMock(return_value=SimpleNamespace(user_id=42)),
                             get_trades=AsyncMock(return_value=rows))
    monkeypatch.setattr(api, 'BacktestEngine', lambda db: engine)
    monkeypatch.setattr(api, 'get_actor', lambda request: {'user_id': 42, 'role': 'USER'})
    response = await api.get_backtest_trades(1, None, limit=2, offset=10, db=None)
    assert response.has_more is more
    assert len(response.trades) == min(count, 2)
    engine.get_trades.assert_awaited_once_with(1, limit=3, offset=10)
