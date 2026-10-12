"""
Backtest worker (Section 162, Phase 9).

Runs scheduled backtest validation jobs:
- Point-in-time snapshot generation
- Strategy backtesting
- Score evaluation
- AI evaluation
- Benchmark comparison
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.database import async_session_factory, commit_session
from app.core.logging import get_logger
from app.domains.stock.models.backtest import BacktestRun, BacktestSnapshot
from app.domains.stock.scoring.backtest import BacktestEngine
from sqlalchemy import select, text

logger = get_logger(__name__)


async def run_scheduled_backtests() -> None:
    """
    Run any queued backtest runs.

    This is a scheduled job that processes backtest runs in the 'queued'
    state. Runs are executed sequentially to avoid resource contention.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.status == "queued")
        )
        runs = result.scalars().all()

        engine = BacktestEngine(session)

        for run in runs:
            try:
                # Execute the queued run IN PLACE via existing_run so the
                # scheduler doesn't spawn a duplicate run row on every tick;
                # the engine transitions this row queued → running →
                # completed/failed itself.
                await engine.run_backtest(
                    name=run.name,
                    strategy=run.strategy,
                    start_date=run.start_date,
                    end_date=run.end_date,
                    initial_capital=run.initial_capital,
                    benchmark_ticker=run.benchmark_ticker or "SPY",
                    parameters=run.parameters or {},
                    snapshot_id=run.snapshot_id,
                    existing_run=run,
                )
                logger.info("Scheduled backtest run %d completed", run.id)
            except Exception as exc:
                # The engine normally persists failure state itself; this
                # catch covers pre-flight errors (e.g. unsupported strategy)
                # raised before the run row was touched, so the row can't sit
                # in 'queued' forever and get reprocessed indefinitely.
                run.status = "failed"
                run.error_message = str(exc)
                await commit_session(session)
                logger.error("Scheduled backtest run %d failed: %s", run.id, exc)

        logger.info("Scheduled backtest processing complete for %d runs", len(runs))


async def create_daily_snapshot() -> None:
    """
    Capture prices and scores once per UTC day, including across schedulers.
    """
    async with async_session_factory() as session:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Transaction-scoped lock: released by the snapshot commit or rollback.
        # Every scheduler checks again after acquiring the same day's lock.
        await session.execute(text("SELECT pg_advisory_xact_lock(:namespace, :day)"),
                              {"namespace": 16201, "day": int(now.strftime('%Y%m%d'))})
        existing = (await session.execute(
            select(BacktestSnapshot.id).where(
                BacktestSnapshot.created_by == "scheduler",
                BacktestSnapshot.as_of >= day_start,
                BacktestSnapshot.as_of < day_start + timedelta(days=1),
            ).limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            await session.rollback()
            logger.info("Daily backtest snapshot already exists for %s: %d", day_start.date(), existing)
            return
        engine = BacktestEngine(session)
        snapshot = await engine.create_snapshot(
            name=f"daily_snapshot_{now.strftime('%Y%m%d')}",
            as_of=now,
            description="Automated daily point-in-time snapshot",
            created_by="scheduler",
        )
        logger.info("Created daily backtest snapshot %d", snapshot.id)
