"""
Task heartbeat tracking.

Wraps scheduler task functions so every periodic pipeline run leaves an
observable trace in the ``task_heartbeats`` table (IMPROVEMENT_PLAN.md Phase 1).
This makes "scheduler stalled" / "task failing" visible via a single DB query
instead of inferring staleness from domain tables (the 0015 outage took weeks
to notice because failures were silent).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.observability import metrics

logger = get_logger(__name__)

T = TypeVar("T")

_UPSERT = text(
    """
    INSERT INTO task_heartbeats (task, last_started_at, last_success_at,
                                 last_failure_at, duration_ms, last_error)
    VALUES (:task, :started, :success, :failure, :duration, :error)
    ON CONFLICT (task) DO UPDATE SET
      last_started_at = EXCLUDED.last_started_at,
      last_success_at = COALESCE(EXCLUDED.last_success_at,
                                 task_heartbeats.last_success_at),
      last_failure_at = COALESCE(EXCLUDED.last_failure_at,
                                 task_heartbeats.last_failure_at),
      duration_ms     = EXCLUDED.duration_ms,
      last_error      = EXCLUDED.last_error
    """
)

_ERROR_TRUNCATE_LEN = 2000


async def _write_row(**params: Any) -> None:
    """Best-effort heartbeat write; never mask the wrapped task's outcome."""
    try:
        async with async_session_factory() as session:
            await session.execute(_UPSERT, params)
            await session.commit()
    except Exception:  # noqa: BLE001 — telemetry must not break the pipeline
        logger.exception("Failed to write heartbeat for task %s", params.get("task"))


async def tracked(name: str, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    """
    Run ``fn(*args, **kwargs)`` with heartbeat persistence.

    Records: last_started_at (before run), then on completion either
    last_success_at + duration_ms or last_failure_at + truncated error text.
    Any failure is also counted in the in-memory pipeline metrics so it
    appears in ``/metrics`` without a DB round-trip.
    """
    started_at = datetime.now(timezone.utc)
    await _write_row(task=name, started=started_at, success=None,
                     failure=None, duration=None, error=None)

    start = time.monotonic()
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        metrics.record_task_failure(name)
        await _write_row(
            task=name,
            started=started_at,
            success=None,
            failure=datetime.now(timezone.utc),
            duration=duration_ms,
            error=f"{type(exc).__name__}: {exc}"[:_ERROR_TRUNCATE_LEN],
        )
        raise

    duration_ms = int((time.monotonic() - start) * 1000)
    await _write_row(task=name, started=started_at,
                     success=datetime.now(timezone.utc),
                     failure=None, duration=duration_ms, error=None)
    logger.debug("Task '%s' completed in %d ms", name, duration_ms)
    return result
