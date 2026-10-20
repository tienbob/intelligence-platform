"""
Internal API router — Rails→Python gateway.

Reuses the existing endpoint routers but authenticates via the internal
service key instead of user JWTs. Mounted at /internal in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.core.security import verify_internal_service_key
from app.domains.stock.api import (
    alerts,
    analysis,
    backtest,
    companies,
    events,
    financials,
    investments,
    market,
    news,
    portfolio,
    prices,
    stocks,
)

internal_router = APIRouter(
    dependencies=[Depends(verify_internal_service_key)],
)

internal_router.include_router(stocks.router)
internal_router.include_router(companies.router)
internal_router.include_router(prices.router)
internal_router.include_router(financials.router)
internal_router.include_router(news.router)
internal_router.include_router(events.router)
internal_router.include_router(market.router)
internal_router.include_router(analysis.router)
internal_router.include_router(investments.router)
internal_router.include_router(portfolio.router)
internal_router.include_router(alerts.router)
internal_router.include_router(backtest.router)


@internal_router.get("/health/live")
async def internal_health_live():
    return {"status": "ok"}


@internal_router.get("/health/ready")
async def internal_health_ready(response: Response):
    from app.core.database import engine
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "degraded"
        response.status_code = 503
    return {"status": "ok" if db_status == "ok" else "degraded", "database": db_status}


@internal_router.get("/health")
async def internal_health():
    return {"status": "ok"}


@internal_router.get("/status")
async def internal_status():
    """Pipeline freshness status (improvement plan I2 / Phase 4).

    Reads ``task_heartbeats`` (written by the scheduler via the ``tracked``
    wrapper) and compares each task's last success against its configured
    cadence. Powers the dashboard freshness badge; also a one-glance answer
    to "is the pipeline alive" without digging through container logs.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    from app.core.database import async_session_factory
    from app.domains.stock.manifest import DOMAIN

    expected = {
        task.name: task.interval_minutes
        for task in DOMAIN.get_intelligence_tasks()
    }

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT task, last_started_at, last_success_at, "
                    "last_failure_at, last_error "
                    "FROM task_heartbeats ORDER BY task"
                )
            )
        ).mappings().all()

    now = datetime.now(timezone.utc)
    tasks = []
    for row in rows:
        name = row["task"]
        interval = expected.get(name, 60)  # default 1h for unknown tasks
        last_success = row["last_success_at"]
        age_minutes = (
            (now - last_success).total_seconds() / 60.0 if last_success else None
        )
        if last_success is None:
            level = "down"  # started once, never succeeded
        elif age_minutes <= interval * 1.5:
            level = "ok"
        elif age_minutes <= interval * 3:
            level = "delayed"
        else:
            level = "down"

        tasks.append(
            {
                "task": name,
                "interval_minutes": interval,
                "last_started_at": row["last_started_at"].isoformat()
                if row["last_started_at"]
                else None,
                "last_success_at": last_success.isoformat()
                if last_success
                else None,
                "last_failure_at": row["last_failure_at"].isoformat()
                if row["last_failure_at"]
                else None,
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "level": level,
                "last_error": row["last_error"],
            }
        )

    if any(t["level"] == "down" for t in tasks):
        overall = "down"
    elif any(t["level"] == "delayed" for t in tasks):
        overall = "delayed"
    else:
        overall = "ok"

    return {"overall": overall, "tasks": tasks}


@internal_router.get("/metrics")
async def internal_metrics():
    from app.core.observability import get_metrics_snapshot
    return get_metrics_snapshot()