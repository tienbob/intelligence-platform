"""
Integration tests: run each *real* upsert path twice (fresh insert, then
conflict) against the fully-migrated schema — the exact scenario that silently
broke event persistence in production (IMPROVEMENT_PLAN.md Phase 3).

These tests are gated behind the ``integration`` marker and a live
``DATABASE_URL`` pointing at a throwaway database migrated to head (see
scripts/integration_test.sh). Unit tests mock the DB and can never catch
constraint/code drift, which is why this file exists.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "integration suite requires DATABASE_URL (scripts/integration_test.sh)",
        allow_module_level=True,
    )


@pytest.fixture()
async def db_session():
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def _seed_company(session) -> int:
    """Create (or reuse) a minimal company row and return its id."""
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                "INSERT INTO companies (ticker, name, sector) "
                "VALUES (:t, :n, :s) "
                "ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id"
            ),
            {"t": "ITZZ", "n": "Integration Test Co", "s": "Technology"},
        )
    ).scalar_one()
    await session.commit()
    return row


async def _seed_news_linked(session, company_id: int, title: str, url: str,
                            content_hash: str) -> int:
    """Insert a news row and link it to the company via company_news.

    NB: the news table has NO company_id column (it is company-agnostic,
    deduped by content_hash); the link lives in the company_news join table.
    """
    from sqlalchemy import text

    news_id = (
        await session.execute(
            text(
                "INSERT INTO news (source, title, url, published_at, content_hash) "
                "VALUES ('integration-test', :t, :u, NOW(), :h) "
                "ON CONFLICT (content_hash) DO UPDATE SET title = EXCLUDED.title "
                "RETURNING id"
            ),
            {"t": title, "u": url, "h": content_hash},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO company_news (company_id, news_id, relevance_score) "
            "VALUES (:c, :n, 1.0) "
            "ON CONFLICT (company_id, news_id) DO NOTHING"
        ),
        {"c": company_id, "n": news_id},
    )
    await session.commit()
    return news_id


# ── 1. Prices: ON CONFLICT (company_id, interval, timestamp) ──────────────

async def test_price_upsert_is_idempotent(db_session):
    """Mirrors ingestion/market.py — upsert on the 3-column composite."""
    from sqlalchemy import text

    company_id = await _seed_company(db_session)
    insert = text(
        "INSERT INTO stock_prices "
        "(company_id, timestamp, interval, open, high, low, close, volume, source) "
        "VALUES (:c, :ts, :i, :p, :p, :p, :p, 1000, 'integration-test') "
        "ON CONFLICT (company_id, interval, timestamp) "
        "DO UPDATE SET close = EXCLUDED.close"
    )
    params = {"c": company_id, "i": "1d", "ts": "2026-01-01 00:00:00+00", "p": 10.0}

    await db_session.execute(insert, params)
    await db_session.commit()

    # Second run: same target, must not raise, must not duplicate.
    await db_session.execute(insert, {**params, "p": 11.0})
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM stock_prices "
                "WHERE company_id = :c AND interval = :i"
            ),
            params,
        )
    ).scalar_one()
    assert rows == 1


# ── 2. News: content_hash unique (company-agnostic) ───────────────────────

async def test_news_content_hash_unique(db_session):
    from sqlalchemy import text

    company_id = await _seed_company(db_session)
    insert = text(
        "INSERT INTO news (source, title, url, published_at, content_hash) "
        "VALUES ('integration-test', :t, :u, NOW(), :h) "
        "ON CONFLICT (content_hash) DO NOTHING"
    )
    params = {
        "t": "Integration headline",
        "u": "https://example.test/it-news",
        "h": "integration-test-hash-0001",
    }

    await db_session.execute(insert, params)
    await db_session.commit()
    await db_session.execute(insert, params)
    await db_session.commit()

    rows = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM news WHERE content_hash = :h"), params
        )
    ).scalar_one()
    assert rows == 1

    # The join table must be able to link the news to the company (twice)
    news_id = (
        await db_session.execute(
            text("SELECT id FROM news WHERE content_hash = :h"), params
        )
    ).scalar_one()
    link = text(
        "INSERT INTO company_news (company_id, news_id, relevance_score) "
        "VALUES (:c, :n, 1.0) ON CONFLICT (company_id, news_id) DO NOTHING"
    )
    await db_session.execute(link, {"c": company_id, "n": news_id})
    await db_session.commit()
    await db_session.execute(link, {"c": company_id, "n": news_id})
    await db_session.commit()

    links = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM company_news "
                "WHERE company_id = :c AND news_id = :n"
            ),
            {"c": company_id, "n": news_id},
        )
    ).scalar_one()
    assert links == 1



# ── 3. Events: (company_id, source_news_id) — the 0015 regression ────────

async def test_event_upsert_conflict_target_matches_constraint(db_session):
    """The production bug: events upsert targeted (company_id, source_news_id)
    while the migration defined a different constraint. Two inserts with the
    same key must succeed via the code's conflict target."""
    from sqlalchemy import text

    company_id = await _seed_company(db_session)
    news_id = await _seed_news_linked(
        db_session,
        company_id,
        "Event-triggering headline",
        "https://example.test/it-event",
        "integration-test-hash-event-1",
    )

    insert = text(
        "INSERT INTO market_events (company_id, source_news_id, event_type, impact) "
        "VALUES (:c, :n, 'EARNINGS_REPORT', 'positive') "
        "ON CONFLICT (company_id, source_news_id) DO NOTHING"
    )
    params = {"c": company_id, "n": news_id}

    await db_session.execute(insert, params)
    await db_session.commit()
    # Second run through the exact code path (fresh insert, then conflict)
    await db_session.execute(insert, params)
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM market_events "
                "WHERE company_id = :c AND source_news_id = :n"
            ),
            params,
        )
    ).scalar_one()
    assert rows == 1


# ── 4. work_jobs: uq_work_jobs_scope_key (reserve_job) ────────────────────

async def test_work_jobs_scope_key_unique(db_session):
    """Mirrors app/core/jobs.py reserve_job — idempotency key replay."""
    from sqlalchemy import text

    insert = text(
        "INSERT INTO work_jobs (id, kind, scope, key, fingerprint, payload, "
        "response, status) "
        "VALUES (:id, 'analysis', :scope, :key, :fp, '{}', '{}', 'queued') "
        "ON CONFLICT (scope, key) DO NOTHING"
    )

    first = {
        "id": "11111111-1111-1111-1111-111111111111",
        "scope": "integration:analysis",
        "key": "it-key-1",
        "fp": "a" * 64,
    }
    await db_session.execute(insert, first)
    await db_session.commit()

    # Replay with a different id/fingerprint: must conflict, not insert.
    second = {**first, "id": "22222222-2222-2222-2222-222222222222",
              "fp": "b" * 64}
    await db_session.execute(insert, second)
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM work_jobs "
                "WHERE scope = :scope AND key = :key"
            ),
            {"scope": first["scope"], "key": first["key"]},
        )
    ).scalar_one()
    assert rows == 1


# ── 5. Heartbeat upsert (Phase 1 wiring) ──────────────────────────────────

async def test_task_heartbeat_upsert(db_session):
    from sqlalchemy import text

    upsert = text(
        "INSERT INTO task_heartbeats (task, last_started_at) "
        "VALUES (:t, NOW()) "
        "ON CONFLICT (task) DO UPDATE SET last_started_at = EXCLUDED.last_started_at"
    )
    await db_session.execute(upsert, {"t": "integration-heartbeat"})
    await db_session.commit()
    await db_session.execute(upsert, {"t": "integration-heartbeat"})
    await db_session.commit()

    rows = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM task_heartbeats WHERE task = :t"),
            {"t": "integration-heartbeat"},
        )
    ).scalar_one()
    assert rows == 1

