from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import asyncio
import pytest
from app.workers import scheduler as module


@pytest.mark.asyncio
async def test_delayed_task_is_scheduled_not_paused(monkeypatch):
    task = SimpleNamespace(name='Delayed task', interval_minutes=10,
                           run_immediately=False, execute=AsyncMock())
    domain = SimpleNamespace(name='test', get_intelligence_tasks=lambda: [task])
    monkeypatch.setattr(module, 'get_registry', lambda: SimpleNamespace(enabled=[domain]))
    scheduler = module.create_scheduler()
    scheduler.start(paused=True)
    try:
        job = scheduler.get_jobs()[0]
        assert job.next_run_time is not None
        assert job.next_run_time > module.datetime.now(module.timezone.utc)
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_leader_stops_on_shutdown(monkeypatch):
    scheduler = MagicMock()
    monkeypatch.setattr(module, 'create_scheduler', lambda: scheduler)
    stop = asyncio.Event()
    stop.set()
    await module.serve_leader(AsyncMock(), stop)
    scheduler.start.assert_called_once()
    scheduler.shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_leader_stops_when_database_connection_is_lost(monkeypatch):
    scheduler = MagicMock()
    monkeypatch.setattr(module, 'create_scheduler', lambda: scheduler)

    async def timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(module.asyncio, 'wait_for', timeout)
    conn = AsyncMock()
    conn.execute.side_effect = RuntimeError('database disconnected')
    with pytest.raises(RuntimeError, match='database disconnected'):
        await module.serve_leader(conn, asyncio.Event())
    scheduler.shutdown.assert_called_once_with(wait=False)
