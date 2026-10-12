"""Daily creation is idempotent across restarts and competing schedulers."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.domains.stock.workers import backtest_worker as worker


@pytest.mark.asyncio
async def test_existing_day_is_skipped_and_lock_released(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: 42)
    monkeypatch.setattr(worker, 'async_session_factory', lambda: session)
    engine = SimpleNamespace(create_snapshot=AsyncMock())
    monkeypatch.setattr(worker, 'BacktestEngine', lambda s: engine)
    await worker.create_daily_snapshot()
    engine.create_snapshot.assert_not_awaited()
    session.rollback.assert_awaited_once()
    lock, bounds = session.execute.await_args_list
    assert 'pg_advisory_xact_lock' in str(lock.args[0])
    query = bounds.args[0].compile()
    values = list(query.params.values())
    start = next(v for v in values if isinstance(v, datetime) and v.hour == 0)
    assert start.tzinfo == timezone.utc
    assert start.minute == start.second == start.microsecond == 0
    assert 'scheduler' in values


@pytest.mark.asyncio
async def test_competing_runs_and_restart_create_only_one_snapshot(monkeypatch):
    lock = asyncio.Lock()
    rows, captures = [], []
    class Session:
        held = False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): await self.rollback()
        async def execute(self, statement, parameters=None):
            if parameters is not None:
                await lock.acquire()
                self.held = True
            return SimpleNamespace(scalar_one_or_none=lambda: rows[0] if rows else None)
        async def rollback(self):
            if self.held:
                self.held = False
                lock.release()
        async def commit(self): await self.rollback()
    monkeypatch.setattr(worker, 'async_session_factory', Session)
    class Engine:
        def __init__(self, session): self.session = session
        async def create_snapshot(self, **kwargs):
            captures.append(kwargs)
            await asyncio.sleep(0)
            rows.append(1)
            await self.session.commit()
            return SimpleNamespace(id=1)
    monkeypatch.setattr(worker, 'BacktestEngine', Engine)
    await asyncio.gather(worker.create_daily_snapshot(), worker.create_daily_snapshot())
    await worker.create_daily_snapshot()
    assert len(captures) == 1
    assert captures[0]['created_by'] == 'scheduler'
    assert captures[0]['name'] == 'daily_snapshot_' + captures[0]['as_of'].strftime('%Y%m%d')
    assert not lock.locked()
