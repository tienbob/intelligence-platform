"""Unit tests for backtest ownership scoping (user_id).

Verifies that the BacktestEngine applies owner filters to runs (strictly
private) and snapshots (own + global) without needing a real database — we
capture the compiled SQL via a fake session.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.domains.stock.models  # noqa: F401,E402  (register tables)
from app.domains.stock.scoring.backtest import BacktestEngine  # noqa: E402


class _Result:
    def __init__(self):
        self._rows = []

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    """Impersonates an AsyncSession, recording each executed statement."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result()


def test_list_runs_filters_by_owner():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.list_runs(owner_id=7))
    sql = str(session.statements[0].compile())
    assert "backtest_runs.user_id = :user_id_1" in sql


def test_list_runs_unscoped_has_no_owner_filter():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.list_runs(owner_id=None))
    sql = str(session.statements[0].compile())
    # user_id is a column so it appears in the SELECT list, but the WHERE
    # clause must NOT filter on it for an unscoped caller.
    assert "user_id =" not in sql and "user_id IS" not in sql


def test_get_run_filters_by_owner():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.get_run(3, owner_id=7))
    sql = str(session.statements[0].compile())
    assert "backtest_runs.id = :id_1" in sql
    assert "backtest_runs.user_id = :user_id_1" in sql


def test_list_snapshots_sees_own_or_global():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.list_snapshots(owner_id=7))
    sql = str(session.statements[0].compile())
    # scoped user sees own snapshots OR global (NULL owner)
    assert "backtest_snapshots.user_id = :user_id_1" in sql
    assert "backtest_snapshots.user_id IS NULL" in sql


def test_list_snapshots_unscoped_has_no_owner_filter():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.list_snapshots(owner_id=None))
    sql = str(session.statements[0].compile())
    # user_id is a column so it appears in the SELECT list, but the WHERE
    # clause must NOT filter on it for an unscoped caller.
    assert "user_id =" not in sql and "user_id IS" not in sql


def test_get_snapshot_sees_own_or_global():
    session = _Session()
    engine = BacktestEngine(session)  # type: ignore[arg-type]
    import asyncio

    asyncio.run(engine.get_snapshot(9, owner_id=7))
    sql = str(session.statements[0].compile())
    assert "backtest_snapshots.id = :id_1" in sql
    assert "backtest_snapshots.user_id IS NULL" in sql


if __name__ == "__main__":
    import asyncio
    from app.domains.stock.models.backtest import BacktestRun, BacktestSnapshot

    # Direct compile checks without needing execution.
    from sqlalchemy import or_, select

    run = select(BacktestRun).where(
        BacktestRun.id == 1, BacktestRun.user_id == 7
    ).compile()
    snap = select(BacktestSnapshot).where(
        BacktestSnapshot.id == 1,
        or_(BacktestSnapshot.user_id == 7, BacktestSnapshot.user_id.is_(None)),
    ).compile()

    r = str(run)
    s = str(snap)
    assert "user_id = :user_id_1" in r
    assert "user_id IS NULL" in s
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("BACKTEST SCOPE TESTS PASS")
