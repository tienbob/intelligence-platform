"""Live, guarded probe for audit O02 - durable coalesced first-time ingestion.

Run against a scratch database only::

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/audit_verify_20261001_fixed \
        .venv/bin/python tests/integration/audit_ingest.py

It proves, on real PostgreSQL:
  * N concurrent reads for one unknown ticker create exactly one work row;
  * the request path never executes the provider/scoring pipeline;
  * the reservation is committed (visible to the worker) before the caller
    is told to retry;
  * a retry reuses that same row instead of piling up new work.

No provider call, no company row, no application data: the probe only writes
to ``work_jobs`` under a synthetic ``ticker:ZZAUDIT`` scope and removes it.
"""

import asyncio
import sys

from sqlalchemy import delete, select, text

from app.core.database import async_session_factory, engine
from app.core.jobs import WorkJob
from app.domains.stock.services import company_resolution as resolve

SYMBOL = "ZZAUDIT"
SCOPE = f"ticker:{SYMBOL}"


async def main() -> None:
    async with engine.connect() as conn:
        name = (await conn.execute(text("SELECT current_database()"))).scalar()
    if not name.startswith("audit_verify_"):
        raise SystemExit(f"refusing to run against {name!r}")

    # Fail loudly if the provider pipeline is ever reached from a read path.
    async def forbidden(ticker, db):
        raise AssertionError("provider pipeline ran on the request path")

    resolve.ingest_missing_ticker = forbidden

    async with async_session_factory() as db:
        await db.execute(delete(WorkJob).where(WorkJob.scope == SCOPE))
        await db.commit()

    async def read():
        async with async_session_factory() as db:
            company = await resolve.get_or_schedule_missing(SYMBOL.lower(), db)
            return company

    results = await asyncio.gather(*(read() for _ in range(12)))
    assert all(company is None for company in results), "a read returned data"

    async with async_session_factory() as db:
        rows = (
            await db.execute(select(WorkJob).where(WorkJob.scope == SCOPE))
        ).scalars().all()
    assert len(rows) == 1, f"expected one coalesced row, found {len(rows)}"
    assert rows[0].status == "queued", rows[0].status
    assert rows[0].kind == "ingestion"
    assert rows[0].payload == {"ticker": SYMBOL}

    # A later read must reuse the live row rather than enqueue another.
    async with async_session_factory() as db:
        assert await resolve.get_or_schedule_missing(SYMBOL, db) is None
    async with async_session_factory() as db:
        count = (
            await db.execute(select(WorkJob).where(WorkJob.scope == SCOPE))
        ).scalars().all()
    assert len(count) == 1, "retry enqueued duplicate work"

    async with async_session_factory() as db:
        await db.execute(delete(WorkJob).where(WorkJob.scope == SCOPE))
        await db.commit()

    # Second half: the queue worker must be the executor. Stub the pipeline
    # (no provider traffic) and confirm the job reaches a terminal state.
    from types import SimpleNamespace

    from app.core.jobs import WorkJob as _Job
    from app.workers import jobs as worker

    async def fake_pipeline(ticker, db):
        assert ticker == SYMBOL
        return SimpleNamespace(id=1, ticker=SYMBOL)

    resolve.ingest_missing_ticker = fake_pipeline
    job_id = "audit-ingest-worker"
    async with async_session_factory() as db:
        await db.execute(delete(_Job).where(_Job.id == job_id))
        db.add(
            _Job(
                id=job_id,
                kind="ingestion",
                scope=SCOPE,
                key="ingestion",
                fingerprint="probe",
                payload={"ticker": SYMBOL},
                response={},
                status="queued",
            )
        )
        await db.commit()

    await worker.process(job_id)

    async with async_session_factory() as db:
        finished = await db.get(_Job, job_id)
        assert finished.status == "completed", finished.status
        await db.execute(delete(_Job).where(_Job.id == job_id))
        await db.commit()

    print(
        "PASS: 12 concurrent first-time reads -> 1 durable ingestion row, "
        "no provider work in-request, retry reuses the reservation, "
        "worker executes the scheduled ingestion"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as exc:  # pragma: no cover - probe harness
        sys.exit(f"FAIL: {exc}")
