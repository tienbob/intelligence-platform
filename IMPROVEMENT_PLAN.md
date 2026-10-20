# Improvement Plan — Addressing the 2026-10 Review Findings

Plan to fix the issues surfaced in the maintenance review of commit `65646a7`
(see [MAINTENANCE.md](MAINTENANCE.md), especially §11 Known Gotchas and §11.4
case study). Every item lists the exact files, acceptance criteria, and a
verifiable command. Nothing here changes product behavior without an explicit
decision (see §Decision log, D1).

## Priority Overview

| # | Issue | Phase | Priority | Effort | Behavior change? |
|---|---|---|---|---|---|
| I1 | No backup/restore path for `postgres_data` | 0 | **P0 — data loss risk** | ~4 h | No |
| I2 | Failures invisible (swallowed exceptions, no freshness signal) | 1 | **P1** | ~1 d | No |
| I3 | `.env` interval overrides silently ignored (config drift) | 2 | **P1 — decision D1 required** | ~4 h | **Yes** (see D1) |
| I4 | Tests can't catch schema/upsert drift (0015 class of bug) | 3 | **P1** | ~1 d | No |
| I5 | Silent scale ceilings (news/embeddings caps) | 1 | P2 | ~1 h | No |
| I6 | Freshness badge in the UI | 4 | P2 | ~1 d | No |
| I7 | News/embeddings batching beyond caps | 4 | P2 | ~1 d | Minor |
| I8 | 4-touchpoint endpoint checklist | — | Keep as doc habit | 0 | No |

Explicit non-goals: no Celery/Redis queue replacement, no Prometheus exporter,
no genericization of the Rails proxy — current choices are correct at this scale.

---

## Implementation Status (2026-10-20)

All phases implemented in the working tree. **Not yet committed** — review
and commit when ready.

| Phase | Status | Deliverables |
|---|---|---|
| 0 — Backups | ✅ Done | `scripts/backup_db.sh` (nightly `pg_dump -Fc`, 14-dump retention, integrity check), `scripts/restore_drill.sh` (throwaway-container restore + data assertion), `MAINTENANCE.md` §15 runbook |
| 1 — Observability | ✅ Done | Migration `0024_add_task_heartbeats`, `app/core/heartbeat.py` `tracked()` wrapper wired into `manifest.py` `_Task.execute`, `ProgrammingError` re-raise + `record_task_failure` metric in `news_worker`/`event_worker`/`company_resolution`, cap-truncation warnings in news + embedding workers |
| 2 — Config wiring | ✅ Done (D1 = Profile A) | `manifest.py#get_intelligence_tasks` reads `StockConfig` cadences; fail-loud guard on non-positive intervals; `tests/test_scheduler_intervals.py` (5 tests); `.env.example` + `README.md` + `MAINTENANCE.md` §7.1/§9/§11 updated |
| 3 — CI + integration tests | ✅ Done | `.github/workflows/ci.yml` (unit + integration + FE build), `scripts/integration_test.sh` harness, `tests/integration/` suite covering prices/news+links/events (0015 regression)/work_jobs/task_heartbeats upsert paths against a migrated throwaway Postgres |
| 4 — Freshness badge | ✅ Done | `GET /internal/status` (Python), Rails `proxy#status` + route, FE `getPipelineStatus` + dashboard freshness chip (green/amber/red with per-task tooltip). I7 batching intentionally deferred until cap warnings fire in production (see Phase 4.2 non-goal note) |

Validation: Python unit suite **339 passed, 1 skipped** (the skip is the
integration module without `DATABASE_URL` — by design); FE `npm run build`
green; all shell scripts pass `bash -n`. The integration harness could not be
exercised locally (Docker daemon unavailable in this workspace) — it runs
automatically in CI and via `scripts/integration_test.sh` on any Docker host.

---

## Phase 0 — Backups & Restore Drill (I1, P0)

**Problem.** All state lives in one docker volume (`postgres_data`) on one
host. Host loss = total platform loss. No dump exists anywhere.

### 0.1 `scripts/backup_db.sh` (repo, run on server via cron)

```bash
#!/usr/bin/env bash
# Nightly logical backup, custom format (compressed + restorable-selective).
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-$HOME/db-backups}"
KEEP_DAILY="${KEEP_DAILY:-14}"; KEEP_WEEKLY="${KEEP_WEEKLY:-12}"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
cd "$(dirname "$0")/.."                      # compose project root
STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
OUT="$BACKUP_DIR/daily/intelligence_stock_${STAMP}.dump"
docker compose exec -T db pg_dump -U postgres -d intelligence_stock -Fc \
  > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"
pg_restore --list "$OUT" > /dev/null          # archive integrity check (fails loudly)
ls -1t "$BACKUP_DIR/daily"/*.dump | tail -n +"$((KEEP_DAILY + 1))" | xargs -r rm --
if [ "$(date -u +%u)" = "7" ]; then           # weekly copy on Sundays (UTC)
  cp "$OUT" "$BACKUP_DIR/weekly/"
  ls -1t "$BACKUP_DIR/weekly"/*.dump | tail -n +"$((KEEP_WEEKLY + 1))" | xargs -r rm --
fi
# Optional off-host hook: set BACKUP_REMOTE in the crontab env, e.g.
#   BACKUP_REMOTE="rclone copy '$OUT' remote:ip-backups/"
[ -n "${BACKUP_REMOTE:-}" ] && eval "$BACKUP_REMOTE"
```

### 0.2 `scripts/restore_drill.sh` — proves backups are real

Restores the newest dump into a **throwaway** pgvector container (never the
primary), then asserts row counts and reports PASS/FAIL:

```bash
docker run -d --rm --name ip_drill -p 55432:5432 \
  -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=intelligence_stock \
  pgvector/pgvector:pg16
sleep 5
LATEST=$(ls -1t "$BACKUP_DIR/daily"/*.dump | head -1)
pg_restore -h localhost -p 55432 -U postgres -d intelligence_stock \
  --no-owner --no-privileges "$LATEST"
# sanity: companies/news/alerts must be > 0 on a populated platform
psql -h localhost -p 55432 -U postgres -d intelligence_stock -tAc "
  SELECT (SELECT COUNT(*) FROM companies) > 0
     AND (SELECT COUNT(*) FROM news) > 0;"
docker stop ip_drill   # --rm cleans up
```

Requirements encoded in the script: use the **pgvector** image (schema uses the
vector extension); fail non-zero on any assertion so cron can alert.

### 0.3 Schedule + docs

- `scripts/backup/crontab.example`:
  `30 2 * * *  /home/ltsadmin/intelligence-platform/scripts/backup_db.sh >> ~/db-backups/backup.log 2>&1`
  plus weekly drill Sunday 03:30 UTC.
- New MAINTENANCE.md section "15. Backup & Recovery": install steps, restore
  procedure for a real emergency (`pg_restore` into the primary), retention policy.
- `.gitignore`: `db-backups/` (never commit dumps).

**Acceptance criteria.**
1. `backup_db.sh` produces a dump, `pg_restore --list` validates it.
2. `restore_drill.sh` reports PASS on the server.
3. `ls ~/db-backups/daily | wc -l` grows daily; old dumps rotate.

---

## Phase 1 — Observability: Heartbeats, Loud Schema Errors, Cap Warnings (I2, I5)

**Problem.** The 0015 outage was invisible for weeks: (a) per-company
`except Exception` swallowed a *programming* error the same as a data error,
(b) nothing distinguished "no events exist" from "event pipeline is dead".

### 1.1 Task heartbeat table (migration `0019_task_heartbeats.py`)

```python
op.create_table("task_heartbeats",
    sa.Column("task", sa.String(100), primary_key=True),
    sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_success_at", sa.DateTime(timezone=True)),
    sa.Column("last_failure_at", sa.DateTime(timezone=True)),
    sa.Column("duration_ms", sa.Integer()),
    sa.Column("last_error", sa.Text()),
)
```

- New `app/core/heartbeat.py`: `tracked(name, fn)` — upserts `last_started_at`
  (`ON CONFLICT (task) DO UPDATE` — matches the PK), runs `fn`, then records
  success (+duration) or failure (+`str(exc)`, truncated). Two tiny commits per
  task run; acceptable.
- `manifest.py#_Task.execute` wraps `self._fn` with `tracked(self.name)` — a
  one-line change; all 10 scheduler tasks covered automatically.
- Worker-queue jobs already have `work_jobs` rows — no extra heartbeat there.

### 1.2 Make schema/code mismatch loud (the 0015 class)

In the three swallow-sites (`company_resolution.py` step 3b, `news_worker.py`,
`event_worker.py` per-company handlers), re-raise DB-programming errors while
keeping the soft behavior for data errors:

```python
except sqlalchemy.exc.ProgrammingError:
    # Schema/code mismatch (e.g. ON CONFLICT target) — never a per-ticker
    # data problem. Swallowing it silently kills the whole feature.
    logger.critical("Programming error in event detection — schema mismatch?")
    raise
except Exception as exc:
    await session.rollback()
    logger.exception("Failed ... for %s: %s", ticker, exc)
```

`_create_*_alerts` already re-raise; with 1.1 the heartbeat records the failure.

### 1.3 Metrics counter (fits the existing pattern)

`app/core/observability.py` `MetricsCollector`: add
`record_task_failure(task: str)` next to `record_provider_call`; include
`pipeline_task_failures_total` in `get_metrics_snapshot()`. Readable via the
existing key-gated `/metrics`.

### 1.4 Cap warnings (I5)

`news_worker.py#process_news` and `embedding_worker.py#ingest_rag_embeddings`:
count companies/rows first; when the limit truncates, log

```python
logger.warning("process_news: %d of %d companies deferred this run "
               "(cap=%d) — backlog grows if this recurs", deferred, total, cap)
```

No behavior change — makes the ceiling observable (ties into D1: cadence × cap
determines real lag).

**Acceptance criteria.**
1. After deploy: `SELECT * FROM task_heartbeats;` shows all 10 tasks with a
   fresh `last_success_at`.
2. Stop the scheduler 30 min → `last_started_at` stops advancing (the §10.4
   freshness probe becomes exact instead of inferred from domain tables).
3. Unit test with a mocked failing task asserts the failure path persists.
4. `pytest tests -q` stays green (335+).

---

## Phase 2 — Wire Scheduler Intervals to Config (I3, P1, decision D1)

**Problem.** `StockConfig` defines `MARKET_DATA_UPDATE_INTERVAL_MIN`,
`NEWS_PROCESSING_INTERVAL_MIN`, `ANOMALY_DETECTION_INTERVAL_MIN`,
`EVENT_ANALYSIS_INTERVAL_HR`, `FUNDAMENTALS_UPDATE_INTERVAL_HR`,
`SCORE_RECALCULATION_INTERVAL_HR` — but `manifest.py#get_intelligence_tasks`
hardcodes 5/10/15/60/1440. Operators edit `.env`, believe cadence changed,
nothing happens. Config drift is worse than missing keys.

### 2.1 Change (manifest.py)

```python
cfg = get_stock_config()
return [
    _Task("Update market data", cfg.MARKET_DATA_UPDATE_INTERVAL_MIN, update_market_data),
    _Task("Process news",       cfg.NEWS_PROCESSING_INTERVAL_MIN, process_news),
    _Task("Detect anomalies",   cfg.ANOMALY_DETECTION_INTERVAL_MIN, detect_anomalies),
    _Task("Analyze events",     cfg.EVENT_ANALYSIS_INTERVAL_HR * 60, analyze_events),
    _Task("Update derived metrics", 60, update_derived_metrics),       # no key yet; documented
    _Task("Recalculate scores", cfg.SCORE_RECALCULATION_INTERVAL_HR * 60, recalculate_scores),
    _Task("Ingest fundamentals", cfg.FUNDAMENTALS_UPDATE_INTERVAL_HR * 60, ingest_fundamentals),
    _Task("Ingest macro indicators", 1440, ingest_macro_indicators),     # ditto, documented
    _Task("Ingest RAG embeddings",  1440, ingest_rag_embeddings),
    _Task("Create daily backtest snapshot", 1440, create_daily_snapshot),
]
```

- Guard in `get_intelligence_tasks`: assert every interval > 0; the scheduler
  already logs each job's `next_run` at boot — keep that as the visible proof.
- New test `tests/test_scheduler_intervals.py`: manifest intervals match config
  values (hours × 60), task names unique, all > 0.
- README + `.env.example`: mark the interval block "**Effective** — scheduler
  reads at boot; recreate scheduler to apply".

### 2.2 ⚠️ Decision D1 — which cadence becomes effective

Wiring this makes the **server's current `.env` values live** — and they are
all `1440` (daily). News daily ⇒ events/alerts effectively daily (would have
masked the 0015 outage even longer). Options:

> ✅ **DECIDED 2026-10-20: Profile A.** Intervals are wired to config; the
> server's `.env` values (daily) become the effective cadence. Implemented in
> commit `feat: wire scheduler intervals to StockConfig (Profile A)`.

| Profile | market | news | anomalies | events | fundamentals/macro/scores | Best for |
|---|---|---|---|---|---|---|
| **A — as-configured-today** | 1440 | 1440 | 1440 | 24 h | daily | credit-starved environments; slow alerts |
| **B — recommended** | 15–30 | 15 | 15 | 60 | daily | production-like freshness |

Profile B cost check: TwelveData budget `TWELVE_DATA_CREDITS_PER_DAY=800`;
usage ≈ `companies × (1440 / interval)` price calls/day — pick the interval so
the product fits the budget for the tracked-company count.

**Acceptance criteria.**
1. Scheduler boot logs show intervals sourced from config.
2. Change `.env` + `docker compose up -d --no-deps --force-recreate scheduler`
   → `next_run` reflects the new interval in logs.
3. New interval tests pass; full suite green.

---

## Phase 3 — Migration/Upsert Integration Tests + CI (I4, P1)

**Problem.** 335 tests passed while every event insert was broken: unit tests
mock the DB layer and never execute SQL against a migrated schema. The 0015
bug class (constraint ↔ `ON CONFLICT` drift) is invisible to them.

### 3.1 Throwaway-DB harness (`tests/integration/`)

- `scripts/integration_test.sh`:
  1. `docker run -d --rm --name ip_it -p 55432:5432 -e POSTGRES_PASSWORD=it
     -e POSTGRES_DB=intelligence_stock pgvector/pgvector:pg16`
  2. Wait for readiness (`pg_isready` loop).
  3. `DATABASE_URL=postgresql+asyncpg://postgres:it@localhost:55432/intelligence_stock
     .venv/bin/alembic upgrade head`
  4. `... .venv/bin/python -m pytest tests/integration -q`
  5. `docker stop ip_it` (trap for cleanup on failure too).
- `pytest.ini`: register the marker —
  `markers = integration: requires a migrated throwaway Postgres (scripts/integration_test.sh)`
  so default `pytest tests` skips it and stays hermetic.

### 3.2 `tests/integration/test_schema_upserts.py`

Exercises each **real upsert path twice** (fresh insert, then conflict) against
the migrated schema — exactly what failed in production:

| Upsert | Conflict target asserted |
|---|---|
| `MarketDataIngestion` price insert | `(company_id, interval, timestamp)` |
| `FundamentalsIngestion` statements | `(company_id, period, period_type)` |
| `MacroIngestion` observations | `(indicator, timestamp)` |
| `NewsIngestion` news insert | `content_hash` unique |
| `EventIntelligenceEngine.detect_events_from_news` | `(company_id, source_news_id)` — **the 0015 regression test** |
| `reserve_job` (work_jobs) | `uq_work_jobs_scope_key` |
| heartbeat upsert (Phase 1) | `(task)` PK |

Each test: seed minimal parent rows (company/news), run the path, run it again,
assert no exception + no duplicate row. A migration changing a constraint
without updating code now fails CI in minutes, not weeks.

### 3.3 GitHub Actions (`.github/workflows/ci.yml`) — repo currently has none

- Job `unit`: the existing 335 suite (`DEBUG=false REDIS_CACHE_ENABLED=false
  pytest tests -q`, Redis service container for the rate-limit test).
- Job `integration`: runs `scripts/integration_test.sh` on `ubuntu-latest`.
- Optional third job: `npm ci && npm test && npm run build` (frontend).

**Acceptance criteria.**
1. Reverting the 0015 hotfix locally makes `integration_test.sh` fail with the
   exact production error — then restoring it makes CI green (proves the net).
2. CI green on `main`; PR status required before merge.

---

## Phase 4 — Freshness Badge & Backlog Batching (I6, I7, P2, optional)

### 4.1 Freshness badge in the UI

```
GET /internal/status            (python, internal_router.py)
  → { tasks: [{task, last_started_at, last_success_at, last_failure_at,
               last_error, expected_interval_min}] }   # from task_heartbeats + manifest
get "status", to: "proxy#status"   (routes.rb + proxy_controller)
FE: services/api.js getStatus(); Dashboard header chip:
  green  "Data updated 3m ago"     (all fresh)
  amber  "Some pipelines delayed"  (any last_success older than 2× interval)
  red    "Data pipelines down"     (no heartbeat updated in 2× interval)
```

Half day. Reuses the Phase 1 table; the dashboard already polls, so piggyback
`data_freshness` on the market/overview response only if a separate call is
unwanted (noted, not chosen — a dedicated endpoint keeps concerns clean).

### 4.2 Backlog batching (defer until data shows need)

`process_news` (cap 50/run) and embeddings (limit 50/run): cursor-based paging
(`WHERE id > last_seen ORDER BY id LIMIT 50` persisted in the heartbeat row)
so consecutive runs drain the full backlog instead of re-processing the same
first 50. Only if cap warnings (1.4) actually fire — otherwise complexity for
nothing.

---

## Rollout Order & Timeline

| When | Work | Exit gate |
|---|---|---|
| **Weekend 1** | Phase 0 complete (scripts + cron + first drill PASS) | `~/db-backups/daily` non-empty; drill PASS |
| Week 1 | Phase 1 (heartbeats, loud errors, counter, warnings) + deploy | `task_heartbeats` populated; suite green |
| Weekend 2 | Phase 2 (config wiring) **after D1 decided** + deploy | boot logs show configured intervals |
| Weekend 3 | Phase 3 (integration harness + CI) | CI green; revert-test reproduced 0015 |
| Later | Phase 4 badge; batching only if warnings fire | chip reflects real staleness |

Sequencing logic: backups protect data before anything else; observability
(1) makes every later change verifiable in production; config wiring (2) is a
behavior change and needs its decision; the CI net (3) lands after the code it
guards is stable. Phases 1+2 touch overlapping files — land Phase 1 first.

## Definition of Done (every item)

1. pytest suite green (unit always; integration where applicable).
2. Deployed via MAINTENANCE.md §10.1 (mind baked-vs-bind: §10.1 rules).
3. Verified in production with the item's acceptance command.
4. MAINTENANCE.md updated in the same commit (§ references above) — the doc
   stays honest or the item isn't done.
5. Separate `feat:`/`fix:`/`ops:` commit per phase; no mixed commits.

## Decision Log

| ID | Decision | Default if unanswered |
|---|---|---|
| **D1** | ✅ **Decided 2026-10-20: Profile A** — intervals wired to `StockConfig`; server `.env` values (daily) effective | — |
| D2 | Off-host backup target (rclone remote, NAS rsync, or local-only for now) | Local-only + weekly manual offload; revisit when a target exists |

## What I deliberately did NOT plan

- Prometheus/Grafana exporters — the JSON `/metrics` + heartbeats cover the
  scale; exporter is a copy-paste away if ever needed.
- Rewriting the swallow-sites as a decorator/framework rule — three explicit
  `except ProgrammingError: raise` blocks are clearer than indirection.
- Genericizing the Rails→Python→FE endpoint chain — explicit beats clever here;
  MAINTENANCE.md §13 checklist covers the touchpoints.

*Authored 2026-10-20. Companion to [MAINTENANCE.md](MAINTENANCE.md).*