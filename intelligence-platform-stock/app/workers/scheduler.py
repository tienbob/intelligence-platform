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
                    next_run_time=(
                        datetime.now(timezone.utc)
                        if run_immediately
                        else None
                    ),
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
            job.next_run_time,
        )

    logger.info(
        "Scheduler configured with %d job(s) across %d domain(s) "
        "(%d disabled task(s) skipped)",
        total_jobs,
        len(registry.enabled),
        skipped_jobs,
    )

    return scheduler


async def run_scheduler() -> None:
    """Run the scheduler (blocking)."""
    scheduler = create_scheduler()
    scheduler.start()

    logger.info("Scheduler started")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")