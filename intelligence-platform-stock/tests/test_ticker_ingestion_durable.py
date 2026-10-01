"""Audit O02: first-time ingestion must not run inside an HTTP request.

Covers the shared resolution contract:
  * a tracked ticker is a plain read (no reservation, no provider work);
  * an untracked ticker reserves one durable job, coalesced per ticker, and
    answers without touching a provider;
  * concurrent misses converge on the same ``(scope, key)`` row;
  * a terminal job is re-queued so a ticker can be re-ingested;
  * the queue worker - not the API process - executes the pipeline.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.domains.stock.services import company_resolution as resolve


class ScriptedSession:
    """Feeds scripted results to the sequential statements resolution issues."""

    def __init__(self, values):
        self.values = list(values)
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        value = self.values.pop(0)
        return SimpleNamespace(
            scalar_one_or_none=lambda: value,
            scalar_one=lambda: value,
        )

    async def commit(self):
        self.commits += 1


def sql(index, session):
    return str(
        session.statements[index].compile(dialect=postgresql.dialect())
    )


def test_tracked_ticker_is_a_plain_read():
    company = SimpleNamespace(id=7, ticker="AAPL")
    db = ScriptedSession([company])
    assert asyncio.run(resolve.get_or_schedule_missing("aapl", db)) is company
    assert len(db.statements) == 1, "must not reserve work for a tracked ticker"
    assert db.commits == 0


def test_untracked_ticker_reserves_durable_work_without_provider_call(monkeypatch):
    async def forbidden(ticker, db):
        raise AssertionError("provider pipeline ran during resolution")

    monkeypatch.setattr(resolve, "ingest_missing_ticker", forbidden)
    db = ScriptedSession([None, "job-1"])

    assert asyncio.run(resolve.get_or_schedule_missing("new", db)) is None

    reservation = sql(1, db)
    assert "INSERT INTO work_jobs" in reservation
    assert "ON CONFLICT ON CONSTRAINT uq_work_jobs_scope_key DO NOTHING" in reservation
    assert db.commits == 1, "reservation must be durable before the response"


def test_concurrent_misses_coalesce_on_one_key():
    """Every request for one ticker must race on the same unique row.

    Coalescing is a property of the reservation key, so the key must derive
    only from the ticker - never from the actor, the request or a random value.
    """

    class ConflictSession(ScriptedSession):
        def __init__(self):
            super().__init__([None])
            self.reservation = None

        async def execute(self, statement):
            self.statements.append(statement)
            if "INSERT" in str(statement):
                compiled = statement.compile(dialect=postgresql.dialect())
                # JSONB has no literal renderer, so compare bound values.
                self.reservation = (
                    str(compiled),
                    compiled.params.get("scope"),
                    compiled.params.get("key"),
                )
                # Another request already owns the row: take the conflict path.
                return SimpleNamespace(
                    scalar_one_or_none=lambda: None,
                    scalar_one=lambda: SimpleNamespace(
                        id="shared", status="running", fingerprint="x"
                    ),
                )
            if "work_jobs" in str(statement):
                # The row already reserved by the competing request is live.
                existing = SimpleNamespace(id="shared", status="running", fingerprint="x")
                return SimpleNamespace(
                    scalar_one_or_none=lambda: existing,
                    scalar_one=lambda: existing,
                )
            value = self.values.pop(0) if self.values else None
            return SimpleNamespace(
                scalar_one_or_none=lambda: value,
                scalar_one=lambda: value,
            )

    async def race():
        db = ConflictSession()
        out = await resolve.get_or_schedule_missing("new", db)
        return out, db.reservation

    async def run_all():
        return await asyncio.gather(*(race() for _ in range(6)))

    results = asyncio.run(run_all())
    assert all(out is None for out, _ in results), "no request may ingest inline"

    reservations = {reservation for _, reservation in results}
    assert len(reservations) == 1, "reservations must be identical per ticker"
    statement, scope, key = reservations.pop()
    assert "INSERT INTO work_jobs" in statement
    assert scope == "ticker:NEW"
    assert key == "ingestion"

    # Case-insensitive input must not create a second key.
    async def other_case():
        db = ConflictSession()
        await resolve.get_or_schedule_missing("NEW", db)
        return db.reservation

    assert asyncio.run(other_case()) == (statement, scope, key)



def test_terminal_job_is_requeued_so_a_ticker_can_retry():
    terminal = SimpleNamespace(id="job-old", status="completed", fingerprint="stale")

    class TerminalSession(ScriptedSession):
        updated = 0

        async def execute(self, statement):
            self.statements.append(statement)
            if "INSERT" in str(statement):
                return SimpleNamespace(
                    scalar_one_or_none=lambda: None,
                    scalar_one=lambda: None,
                )
            return SimpleNamespace(
                scalar_one_or_none=lambda: None,
                scalar_one=lambda: terminal,
            )

        async def commit(self):
            self.commits += 1

    db = TerminalSession([])
    assert asyncio.run(resolve.get_or_schedule_missing("reborn", db)) is None
    assert terminal.status == "queued", "terminal job must be retried"
    assert db.commits >= 1


def test_worker_owns_the_ingestion_pipeline():
    """The API process must not be the executor for this job kind."""
    from app.workers import jobs as worker

    source = open(worker.__file__).read()
    assert "elif job.kind == 'ingestion'" in source
    assert "ingest_missing_ticker" in source


def test_pending_response_is_not_reported_as_missing_company():
    error = resolve.ingestion_pending("zzz")
    assert error.status_code == 404
    assert error.headers == {"Retry-After": "30"}
    assert "not tracked yet" in error.detail
