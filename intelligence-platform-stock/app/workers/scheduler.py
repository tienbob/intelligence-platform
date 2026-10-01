"""
Domain-agnostic background job scheduler.

Auto-discovers intelligence tasks from all enabled domains and registers
them as APScheduler jobs. No domain-specific imports needed — the registry
provides the task list.

To add a new domain's background jobs:
    1. Implement IntelligenceTask classes in your domain's workers.py
    2. Return them from your domain manifest's get_intelligence_tasks()
    3. Set enabled=True when the task implementation is ready
    4. Restart — the scheduler auto-discovers them
"""

from __future__ import annotations

import asyncio
import signal

from sqlalchemy import text
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import get_logger
from app.intelligence.registry import get_registry

logger = get_logger(__name__)
settings = get_settings()


def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the background job scheduler.

    Auto-discovers all intelligence tasks from enabled domains
    and registers enabled tasks with their configured intervals.
    """
    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    registry = get_registry()

    total_jobs = 0
    skipped_jobs = 0

    for domain in registry.enabled:
        try:
            tasks = domain.get_intelligence_tasks()
        except Exception as exc:
            logger.warning(
                "Failed to get tasks for domain '%s': %s",
                domain.name,
                exc,
            )
            continue

        for task in tasks:
            # Tasks default to enabled for backwards compatibility.
            # Placeholder/unimplemented tasks should explicitly set
            # enabled = False in their domain implementation.
            if not getattr(task, "enabled", True):
                skipped_jobs += 1
                logger.info(
                    "Skipping disabled task '%s' for domain '%s'",
                    task.name,
                    domain.name,
                )
                continue

            job_id = f"{domain.name}_{task.name.lower().replace(' ', '_')}"

            run_immediately = getattr(task, "run_immediately", True)

            try:
                scheduler.add_job(
                    task.execute,
                    IntervalTrigger(
                        minutes=task.interval_minutes,
                    ),
                    id=job_id,
                    name=f"[{domain.name}] {task.name}",
                    max_instances=1,
                    coalesce=True,
                    **({"next_run_time": datetime.now(timezone.utc)} if run_immediately else {}),
                )

                total_jobs += 1

                logger.debug(
                    "Registered job '%s' "
                    "(every %d min, run_immediately=%s)",
                    job_id,
                    task.interval_minutes,
                    run_immediately,
                )

            except Exception as exc:
                logger.error(
                    "Failed to register job '%s': %s",
                    job_id,
                    exc,
                )

    # Log the final schedule so startup logs clearly show what will run.
    for job in scheduler.get_jobs():
        logger.info(
            "Scheduled job: %s | next_run=%s",
            job.id,
            getattr(job, "next_run_time", "first interval after startup"),
        )

    logger.info(
        "Scheduler configured with %d job(s) across %d domain(s) "
        "(%d disabled task(s) skipped)",
        total_jobs,
        len(registry.enabled),
        skipped_jobs,
    )

    return scheduler


# Stable session-level lock, shared by scheduler replicas for this database.
SCHEDULER_LOCK_ID = 734201930


async def serve_leader(conn, stop: asyncio.Event) -> None:
    """Run only while this dedicated connection retains database ownership."""
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler leadership acquired")
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                # A lost DB session loses its advisory lock. Exit rather than
                # silently reconnecting and continuing as a second scheduler.
                await conn.execute(text("SELECT 1"))
                await conn.commit()
    finally:
        scheduler.shutdown(wait=False)
        # AsyncIOScheduler schedules executor cancellation on the event loop.
        await asyncio.sleep(0)
        logger.info("Scheduler stopped")


async def run_scheduler() -> None:
    from app.core.database import engine

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with engine.connect() as conn:
            while not stop.is_set():
                acquired = (await conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_LOCK_ID}
                )).scalar()
                await conn.commit()
                if acquired:
                    try:
                        await serve_leader(conn, stop)
                    finally:
                        # Closing a failed connection also releases ownership.
                        if not conn.invalidated:
                            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULER_LOCK_ID})
                            await conn.commit()
                    return
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
    finally:
        await engine.dispose()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    asyncio.run(run_scheduler())
