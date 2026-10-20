# Maintenance Guide — Intelligence Platform

Operational reference for maintaining, debugging, and extending the platform.
Every flow below is traced from the actual code (file paths included) so it can
be verified rather than trusted.

> Companion docs: [README](README.md) · [Architecture V3](intelligence-platform-stock/docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md) ·
> [Framework analysis path](intelligence-platform-stock/docs/FRAMEWORK_ANALYSIS_PATH.md) · [Provider migration](intelligence-platform-stock/docs/PROVIDER_MIGRATION.md)

---

## 1. System Architecture

```
┌──────────────┐   :3000    ┌──────────────────────────────┐
│   Browser    │───────────▶│ frontend (nginx)             │
└──────────────┘            │  serves React build          │
                            │  proxies /api/v1/* ──────────┼──┐
                            └──────────────────────────────┘  │
                                                              ▼ :3000 (internal)
                            ┌──────────────────────────────┐
                            │ rails (Puma API gateway)     │
                            │  auth, users, JWT, proxy     │
                            └──────────────┬───────────────┘
                                           │ http://python:8001/internal/*
                                           │ X-Service-Key + user identity headers
                                           ▼ :8001 (internal only)
                            ┌──────────────────────────────┐     ┌─────────────┐
                            │ python (FastAPI, uvicorn)    │────▶│ redis :6379 │
                            │  /internal/*  (service key)  │     └─────────────┘
                            │  /health /metrics /domains   │
                            └──────┬───────────────┬───────┘
                                   │               │
                    ┌──────────────▼───┐   ┌───────▼────────┐
                    │ worker           │   │ scheduler      │
                    │ work_jobs poller │   │ APScheduler    │
                    │ (2s interval)    │   │ (leader elect) │
                    └────────┬─────────┘   └───────┬────────┘
                             │      ┌──────────────┘
                             ▼      ▼
                   ┌──────────────────────────┐
                   │ db (pgvector/pg16) :5432 │
                   └──────────────────────────┘
```

### 1.1 Compose services (`docker-compose.yml`)

| Service | Container name | Command | Notes |
|---|---|---|---|
| `db` | `intelligence_stock_db` | pgvector/pg16 | Port 5432 published. Health: `pg_isready`. |
| `redis` | `intelligence_stock_redis` | redis:7-alpine (AOF) | Port 6379 published. Cache + idempotency store. |
| `python-migrate` | `intelligence_stock_python_migrate` | `bash scripts/migrate.sh` (Alembic) | One-shot; must complete before python/worker/scheduler. |
| `python` | `intelligence_stock_python` | `uvicorn app.main:app --port 8001` | **Bind mount** `./intelligence-platform-stock:/app` → code changes visible after restart, no rebuild. |
| `worker` | — | `python -m app.workers.jobs` | **Baked image** → code changes need `--build`. Drains `work_jobs`. |
| `scheduler` | — | `python -m app.workers.scheduler` | **Baked image** → needs `--build`. Runs all periodic tasks. |
| `rails-migrate` | `intelligence_stock_rails_migrate` | `bash bin/migrate.sh` | One-shot; must complete before rails. |
| `rails` | `intelligence_stock_rails` | `bundle exec puma` | Port 3000 internal only. |
| `frontend` | `intelligence_stock_frontend` | nginx | **Only published port: 3000:80.** Build args inject `VITE_REFRESH_*`. |

### 1.2 Request path (every browser call)

```
Browser fetch('/api/v1/...')
  → nginx (frontend container) proxies /api/v1 → rails:3000
  → Rails BaseController#authenticate_request!   (JWT verify, user load)
  → Api::V1::ProxyController#render_python       (proxy_controller.rb)
      → PythonClient.request_full(method, path,
          user: current_user,                    # identity forwarded as headers
          extra_headers: [Idempotency-Key])
  → FastAPI /internal/* (app/domains/stock/api/internal_router.py)
      Depends(verify_internal_service_key)       # X-Service-Key header
  → domain routers (stocks, companies, prices, financials, news, events,
    market, analysis, investments, portfolio, alerts, backtest)
  → PostgreSQL
```

Security properties to preserve when modifying:
- **Python never sees user JWTs.** It authenticates Rails via `INTERNAL_SERVICE_KEY`
  and receives the acting user in forwarded headers (`app/core/security.py#get_actor`).
- `/internal` is only reachable on the Docker network (nginx does not proxy it).
- `/metrics` is key-gated outside development (`app/main.py#metrics_endpoint`).
- Production boot guard (`app/main.py`): refuses to start when `ENVIRONMENT=production`
  runs with dev-default `INTERNAL_SERVICE_KEY` or `JWT_SECRET_KEY`.
- Responses use the envelope `{"data": …, "meta": …}` (`response_envelope.py`);
  the FE unwraps `.data` in `services/api.js#request`.

---

## 2. Repository Layout

```
intelligence-platform/
├── docker-compose.yml                  # 9 services (§1.1)
├── .env                                # single source of container config
├── intelligence-platform-stock/        # Python: framework + stock domain
│   ├── app/
│   │   ├── main.py                     # FastAPI app, domain discovery, guards
│   │   ├── core/                       # config, db, jobs, security, redis, envelopes
│   │   ├── intelligence/               # V3 FRAMEWORK: pipeline, registry, RAG, LLM…
│   │   └── domains/stock/              # domain pack (all stock features live here)
│   │       ├── manifest.py             # wires domain: providers, tasks, routers
│   │       ├── api/                    # FastAPI routers (mounted at /internal)
│   │       ├── workers/                # scheduled task implementations
│   │       ├── ingestion/              # provider → raw → canonical persistence
│   │       ├── scoring/                # anomaly, event, sentiment, backtest, risk…
│   │       ├── services/               # company_resolution, company_analysis
│   │       ├── models/                 # SQLAlchemy models
│   │       └── providers/              # FMP, Finnhub, FRED, TwelveData, SEC, Massive
│   ├── migrations/versions/            # Alembic revisions 0001…
│   └── tests/                          # pytest (mocked providers)
├── intelligence-platform-api/          # Rails gateway (auth + thin proxy)
│   ├── app/controllers/api/v1/         # auth_controller, base_controller, proxy_controller
│   ├── config/routes.rb                # full public API surface
│   └── db/schema.rb                    # mirrors shared tables
└── intelligence-platform-frontend/     # React (Vite) SPA
    └── src/
        ├── pages/                      # one file per route (§4)
        ├── services/                   # api.js, auth.jsx, polling, refresh, token
        └── config.js                   # VITE_REFRESH_* intervals
```

## 3. Database Ownership Map

One PostgreSQL database (`intelligence_stock`) shared by Rails and Python.

| Owner | Tables |
|---|---|
| **Rails** (system of record) | `users`, `auth_sessions` (JWT rotation/revocation) |
| **Python** (everything else) | `companies`, `stock_prices`, `financial_statements`, `technical_indicators`, `risk_metrics`, `news`, `company_news`, `raw_news`, `raw_market_data`, `raw_sec_filings`, `market_events`, `event_price_correlations`, `anomaly_scores`, `economic_indicators`, `analyses`, `investment_scores`, `backtest_runs`, `backtest_trades`, `backtest_snapshots`, `alerts`, `alert_reads`, `work_jobs` |

Migrations run in strict order via the compose dependency chain:
`db (healthy) → python-migrate → python / worker / scheduler` and
`db (healthy) → python-migrate → rails-migrate → rails`.
**Never mutate schema by hand on the server — write an Alembic migration**
(see §11.4 for a real-world constraint lesson).

---

## 4. Frontend Route → Feature Map

| Route | Page component | Backing endpoints |
|---|---|---|
| `/` | Landing (public) | — |
| `/login`, `/register` | Login, Register | `POST /auth/login`, `POST /auth/register` |
| `/dashboard` | Dashboard | `GET /market/overview`, `/market/indices`, `/market/top-movers`, `GET /alerts/?limit=5` |
| `/companies`, `/companies/:ticker` | Companies, CompanyDetail | `GET /companies`, `/companies/:ticker`, `/stocks/:ticker*`, `/financials/:ticker/*` |
| `/search` | Search (ticker import) | `GET /companies?q=`, `GET /stocks/:ticker` |
| `/analysis`, `/analysis/:id` | Analysis, AnalysisDetail | `POST /analysis/company`, `GET /analysis/jobs`, `GET /analysis/:id` |
| `/opportunities` | Opportunities | `GET /investments/opportunities` |
| `/news`, `/news/:id` | News, NewsDetail | `GET /news`, `GET /news/:id` |
| `/events`, `/events/:id` | Events, EventDetail | `GET /events`, `GET /events/:id` |
| `/market` | Market | market endpoints above |
| `/backtest` | Backtest | `GET/POST /backtest/runs`, `/backtest/runs/:id(/trades)`, `/backtest/snapshots` |
| `/alerts` | Alerts | `GET/POST /alerts/`, `POST /alerts/:id/read` |
| `/portfolio` | → redirect to `/opportunities` | `POST /portfolio/optimize` (API only, no UI) |

All app routes are wrapped in `RequireAuth`. Data polling uses
`services/polling.js#startPolling` with intervals from `src/config.js`
(`VITE_REFRESH_DASHBOARD_MS=30000`, jobs/detail 5000–30000; `0` disables).
Routes are code-split (`lazy()`), so a change to one page only rebuilds its chunk.

---

## 5. Authentication Flow (Rails-owned)

```
Register  POST /auth/register ──▶ User created (role USER) ─▶ 201 token pair
Login     POST /auth/login    ──▶ Devise valid_password? ───▶ 200 token pair
Refresh   POST /auth/refresh  ──▶ JwtService.rotate         ─▶ 200 new pair
Logout    POST /auth/logout   ──▶ revoke auth_sessions row ─▶ 204
Me        GET  /auth/me       ──▶ current_user as_json     ─▶ 200
```

Files: `intelligence-platform-api/app/controllers/api/v1/auth_controller.rb`,
`app/services/jwt_service.rb`, `config/initializers/gateway.rb`.

- Access + refresh JWTs are tied to an `auth_sessions` row; refresh **rotates**
  the pair and replay of an old refresh token is rejected (single-use).
- Auth endpoints are throttled (`throttle_auth!` by remote IP).
- Frontend (`src/services/`): tokens in `localStorage` (`token.js`), one silent
  refresh + retry on 401 (`api.js#request`), generation guard so a stale tab
  can never refresh/clear a newer session (`token.js#getSessionGeneration`).
  Auth-route 401s never trigger the redirect (loop protection).
- **User scoping in Python:** every user-owned row (analyses, user alerts,
  backtests) filters by `get_actor(request)`; system rows (`user_id IS NULL`)
  are visible to everyone; admins see all. Dismiss/read actions create a
  per-viewer receipt row, never global state.

---

## 6. Feature Flows

### 6.1 Market Dashboard (`/dashboard`)

```
Dashboard.jsx (polls every REFRESH_DASHBOARD_MS via startPolling)
  ├─ getMarketOverview()  → GET /market/overview   → market.py#get_market_overview
  │                        (assembles DB snapshot + macro/VIX; catch → section banner)
  ├─ getAlerts({limit:5}) → GET /alerts/?limit=5   → alerts.py#list_alerts
  ├─ getMarketIndices()   → GET /market/indices    → market.py (TwelveData w/ Redis cache + fallback)
  └─ getTopMovers()       → GET /market/top-movers → market.py (computed from stock_prices)
```

- Each section fetches **independently** (`Promise.allSettled`); a slow/failing
  section never blanks the page. Failure renders an actionable banner +
  per-section "Retry" (`settledSections` / `failedSections` state).
- Three-state empty card: `Loading…` → `Alerts unavailable` (fetch failed) →
  `No Active Alerts` (fetch succeeded, zero rows). Preserve these distinctions —
  they are the primary user-visible signal of a dead backend vs empty data.

### 6.2 Ticker Search & First-Time Ingestion (`/search`)

```
Search.jsx → createCompanySearch() (services/companySearch.js)
  1. GET /companies?q=TERM                  → existing tracked companies
  2. none + ticker-like term → GET /stocks/:TICKER (quote)
       ├─ 200 → show quote
       └─ 404 "ingestion has started" (Retry-After: 30)
            → importing mode: poll GET /companies/:TICKER every interval
              until data appears or 5-minute give-up message
```

Server side (`services/company_resolution.py`):
```
get_or_schedule_missing(ticker)            # request path, NO provider calls
  ├─ company exists → return row
  └─ missing → INSERT work_jobs(kind='ingestion', scope='ticker:X', key='ingestion')
              ON CONFLICT (scope,key) DO NOTHING        # N concurrent reqs → 1 job
              → raise 404 + Retry-After
ingest_missing_ticker(ticker, db)          # worker path (work_jobs poller)
  1. MarketDataIngestion.ingest_historical_prices(ticker, 365d, '1d')  # creates Company
  2. FundamentalsIngestion: profile + FMP statements        (optional, logged)
  3. NewsIngestion.ingest_company_news(ticker, limit=50)    (optional)
  3b. EventIntelligenceEngine.detect_events_from_news(hours=168)
  4. TechnicalAnalysisEngine.calculate_indicators + FundamentalAnalysisEngine
  Each stage commits independently; later failures keep earlier data.
```

- Failed ingestion jobs are reported (row stays retryable) — polling does not
  silently requeue (`uq_work_jobs_scope_key` + status checks).
- The FE caps the import wait at 5 min and tells the user to re-search.

### 6.3 Companies & Company Detail (`/companies/:ticker`)

```
CompanyDetail.jsx
  ├─ GET /companies/:ticker            → companies.py (profile row)
  ├─ GET /stocks/:ticker               → stocks.py   (quote: TwelveData → Redis cache)
  ├─ GET /stocks/:ticker/prices        → stocks.py   (OHLCV series from stock_prices)
  ├─ GET /financials/:ticker/metrics   → financials.py (derived ratios)
  ├─ GET /financials/:ticker/technical → financials.py (technical_indicators)
  ├─ GET /financials/:ticker/statements → financials.py (financial_statements)
  └─ GET /prices/:ticker               → prices.py   (raw price history)
```

All read persisted data only — API routes never call providers directly
(ingestion is worker-owned; audit O02).

### 6.4 Deep Analysis (AI) — `/analysis`

The paid, LLM-backed analysis. Two entry points share one engine (the V3
framework pipeline): user-triggered API and scheduled task.

```
Analysis.jsx → POST /analysis/company  (Idempotency-Key header attached)
  → Python analysis.py#create_company_analysis  (202 Accepted)
      1. get_or_schedule_missing(ticker)      # untracked → 404 "ingestion has started"
      2. reserve_job()                        # Idempotency-Key dedup (Redis, else memory)
      3. INSERT analyses(analysis_id, user_id, status='queued', _request)
      4. INSERT work_jobs(kind='analysis')    → returns {analysis_id, status:'queued'}
AnalysisDetail.jsx polls GET /analysis/:id + jobs list every REFRESH_ANALYSIS_*_MS
  status transitions persisted by run_company_analysis():
  queued → collecting_data → retrieving_context → llm_analysis → … → completed/failed/cancelled
worker (jobs.py#execute, kind='analysis')
  → run_company_analysis(analysis_id, ticker, include_* flags)
      → execute_company_analysis() (services/company_analysis.py)
          V3 IntelligencePipeline — 12 stages (app/intelligence/pipeline.py):
          Request → Domain Resolver → Ingestion → Normalization → Entity Resolution
          → Evidence Collection → RAG Retrieval → Context Builder → LLM
          → Structured Validation → Domain Scoring → Result
          every stage records success | degraded | skipped | failed:<error>
      → AnalysisPersistence writes the canonical row (scores, evidence, claims)
  failure → fail_target(): status='failed' + human _failure_reason
```

Operational notes:
- `cancel` (`POST /analysis/:id/cancel`) and `DELETE` are owner-or-admin only
  (`_lock_owned_analysis`); cancel raises `AnalysisCancelled` inside the worker.
- LLM config: `LLM_PROVIDER/LLM_API_KEY/LLM_MODEL` + transient-error retries
  (`LLM_MAX_ATTEMPTS`, `LLM_RETRY_*`) and fallback model (`LLM_FALLBACK_MODEL`).
- The `include_news/fundamentals/technical/macro` flags exclude whole snapshot
  sections (`manifest.py#excluded_sections`) — cheap way to cut cost/latency.
- Never run paid provider/LLM work inside GET handlers or the API process;
  queue it (`work_jobs`) like this flow does.

### 6.5 Opportunities (`/opportunities`)

```
Opportunities.jsx → GET /investments/opportunities (cache: no-store, 30s refresh)
  → investments.py#get_investment_opportunities
      joins investment_scores × companies × risk_metrics
      + today's completed deep analyses (see completed_today)
      → ranked opportunity rows with score breakdown + data confidence
```

Scores come from `scoring/investment_scoring.py` (weights in §9) recalculated
daily by the scheduler; "today's completed deep dives" surface research done
within the current UTC day.

### 6.6 News Aggregator (`/news`)

```
News.jsx → GET /news?ticker=&page…   → news.py#list (paginated lean rows)
NewsDetail.jsx → GET /news/:id        → news.py (full row + company links)
```

Feeding this table is the scheduler's news pipeline (§7 "Process news"):
Finnhub provider → dedup by `content_hash` → `news` + `company_news` links
(ticker link relevance 1.0; headline name match 0.85) → sentiment/materiality
enrichment → RAG embedding.

### 6.7 Market Events (`/events`)

Events are **derived from news** — they never come from a provider directly.

```
news + company_news tables (input)
  → EventIntelligenceEngine.detect_events_from_news(company_id, hours=168)
     (scoring/event_detection.py)
     ├─ gate: company_news.relevance_score >= MIN_EVENT_RELEVANCE (0.8)
     ├─ classify_event(title, summary) — skip when OTHER
     ├─ score_event_impact → impact label/score + materiality (0..1)
     ├─ compute_effective_weight(relevance, credibility, materiality, time_decay)
     ├─ INSERT market_events … ON CONFLICT (company_id, source_news_id) DO NOTHING
     │    unique constraint uq_market_events_company_news (migration 0015) —
     │    one canonical event per news article per company. Keep the conflict
     │    target 2-column or PG rejects the insert (see §11.4 incident).
     └─ materiality >= 0.5 → correlate_event_with_price → _update_impact_from_price
          (realized price reaction overrides headline sentiment)
Events.jsx → GET /events?ticker=&event_type=&offset → events.py (lean rows, lookahead paging)
EventDetail.jsx → GET /events/:id    → events.py (materiality + effective_weight included)
```

Callers of event detection: `analyze_events` (scheduler, hourly),
`process_news` (scheduler, 10-min, per ingested company), and first-time
ingestion (`ingest_missing_ticker` step 3b).

### 6.8 Alerts (`/alerts` + dashboard card)

Three alert sources, one table:

| Source | Producer | Type |
|---|---|---|
| User-created | `POST /alerts/` (`user_id` set) | any |
| Anomaly triggers | scheduler `detect_anomalies` → `anomaly_scores.triggered` → `_create_anomaly_alerts` | `PRICE_ANOMALY` |
| Material events | scheduler `analyze_events` → `market_events.effective_weight ≥ 0.4` → `_create_event_alerts` | `MARKET_EVENT` |

```
Alerts.jsx  → GET /alerts/?unread_only&limit&offset  → alerts.py#list_alerts
            → POST /alerts/:id/read → inserts alert_reads(alert_id, user_id)
Dashboard   → GET /alerts/?limit=5 (same endpoint)
Visibility rule (alerts.py#_visible): own rows + system rows
(user_id IS NULL, legacy_private=false); admin sees everything.
Anomaly trigger: movement_score ≥ ANOMALY_MOVEMENT_THRESHOLD (80.0) where
score = price_change·0.35 + volume·0.25 + volatility·0.20 + technical·0.20
(~4%+ daily move with volume/volatility confirmation → high severity ≥ 80).
```

### 6.9 Backtesting (`/backtest`)

```
Backtest.jsx → POST /backtest/runs   → backtest.py → BacktestRun(status='queued')
worker (jobs.py kind='backtest') → BacktestEngine.run_backtest(existing_run=row)
  uses point-in-time BacktestSnapshot data → backtest_trades + result metrics
Backtest.jsx polls GET /backtest/runs (+ /trades paged, + /backtest/runs/:id)
Snapshots: scheduler create_daily_snapshot (per-UTC-day advisory lock, §7)
   → look-ahead-free replay data; POST /backtest/snapshots creates manual ones
```

Scheduled runs: the scheduler also drains `status='queued'` runs via
`run_scheduled_backtests` (`backtest_worker.py`) — executes rows in place so
no duplicate run rows appear.

### 6.10 Portfolio Optimizer (API only)

`POST /portfolio/optimize` → `portfolio.py` stateless optimizer (mean-variance
constraints from stock config). The portfolio UI was removed — `/portfolio`
redirects to `/opportunities`. Keep the endpoint auth-gated like the rest.

---

## 7. Background Jobs

### 7.1 Scheduler tasks (`scheduler.py` + `manifest.py#get_intelligence_tasks`)

APScheduler (AsyncIOScheduler) with **PostgreSQL advisory-lock leader election**
(`SCHEDULER_LOCK_ID=734201930`) — exactly one scheduler replica executes jobs;
followers idle. `run_immediately=True` (default) makes each task run once at
scheduler startup, so a fresh environment populates on day one.

| # | Task | Every | Implementation | Reads → Writes |
|---|---|---|---|---|
| 1 | Update market data | `MARKET_DATA_UPDATE_INTERVAL_MIN` (default 5 min) | `workers/market_worker.py#update_market_data` | stale-first tickers → `stock_prices` (ON CONFLICT `(company_id,interval,timestamp)`); stops on `RateLimitError` until next run |
| 2 | Process news | `NEWS_PROCESSING_INTERVAL_MIN` (default 10 min) | `workers/news_worker.py#process_news` | Finnhub → `news`,`company_news` → sentiment/materiality enrichment → event detection (**max 50 companies/run**) |
| 3 | Detect anomalies | `ANOMALY_DETECTION_INTERVAL_MIN` (default 15 min) | `workers/event_worker.py#detect_anomalies` | `stock_prices` (30d) → `anomaly_scores` → `PRICE_ANOMALY` alerts |
| 4 | Analyze events | `EVENT_ANALYSIS_INTERVAL_HR` (default 1 h) | `workers/event_worker.py#analyze_events` | `company_news` (7d) → `market_events` → `MARKET_EVENT` alerts |
| 5 | Update derived metrics | 60 min (fixed — no key yet) | `workers/analysis_worker.py#update_derived_metrics` | → `technical_indicators`, `risk_metrics` |
| 6 | Recalculate scores | `SCORE_RECALCULATION_INTERVAL_HR` (default 24 h) | `analysis_worker.py#recalculate_scores` | → `investment_scores` (weights §9) |
| 7 | Ingest fundamentals | `FUNDAMENTALS_UPDATE_INTERVAL_HR` (default 24 h) | `workers/ingestion_worker.py#ingest_fundamentals` | FMP → `financial_statements`, profile |
| 8 | Ingest macro indicators | 24 h (fixed — no key yet) | `ingestion_worker.py#ingest_macro_indicators` | FRED → `economic_indicators` |
| 9 | Ingest RAG embeddings | 24 h (fixed — no key yet) | `workers/embedding_worker.py#ingest_rag_embeddings` | unindexed news/events/analyses → embedding vectors (limit 50/run) |
| 10 | Create daily backtest snapshot | 24 h (fixed — no key yet) | `workers/backtest_worker.py#create_daily_snapshot` | per-day `pg_advisory_xact_lock` → `backtest_snapshots` (point-in-time) |

> ✅ **Config-driven cadence (improvement plan Phase 2, decision D1 = Profile A):**
> the six keys above are **effective** — read from `StockConfig` once at
> scheduler boot. After changing `.env`:
> `docker compose up -d --no-deps --force-recreate scheduler`. Tasks marked
> *fixed* have no config key yet. The production server currently runs
> Profile A: all six keys = 1440 (daily) in its `.env`, so the four frequent
> tasks run once a day there.

Registration/execution is observable: startup logs print
`Scheduled job: <id> | next_run=…`; tasks log their own summaries
(e.g. `Anomaly detection complete for N companies; M alerts`).

### 7.2 Worker queue (`app/workers/jobs.py`)

- Polls `work_jobs` every **2 s** for `status IN (queued, running)`, oldest first.
- Per-job Postgres advisory lock (hash of job id) — safe across replicas.
- Kinds: `analysis` (framework pipeline), `ingestion` (ticker import), `backtest`.
- A job found already `running` was abandoned by a dead worker → `fail_target()`
  marks the target Analysis/BacktestRun `failed` with a user-facing reason,
  rather than re-executing paid work blindly.

### 7.3 Manual task execution (one-off runs on the server)

```bash
docker compose exec python python -c "import asyncio; from app.domains.stock.workers.event_worker import analyze_events; asyncio.run(analyze_events())"
docker compose exec python python -c "import asyncio; from app.domains.stock.workers.event_worker import detect_anomalies; asyncio.run(detect_anomalies())"
docker compose exec python python -c "import asyncio; from app.domains.stock.workers.news_worker import process_news; asyncio.run(process_news())"
docker compose exec python python -c "import asyncio; from app.domains.stock.workers.market_worker import update_market_data; asyncio.run(update_market_data())"
```

---

## 8. Data Pipeline Layers

```
Providers (Finnhub·FMP·FRED·TwelveData·SEC·Massive)
   │  ingestion/* modules (worker/scheduler owned, never API GET handlers)
   ▼
raw_news / raw_market_data / raw_sec_filings     # verbatim provider payloads (audit lineage)
   ▼
canonical: stock_prices · financial_statements · news+company_news · economic_indicators
   ▼
derived: technical_indicators · risk_metrics · anomaly_scores · market_events · investment_scores
   ▼
AI: analyses (framework 12-stage pipeline, evidence-attributed) · embeddings (pgvector)
   ▼
surfacing: dashboard · opportunities · events · alerts · backtests
```

- Dedup discipline: prices `(company_id, interval, timestamp)`, statements
  `(company_id, period, period_type)`, macro `(indicator, timestamp)`,
  news `content_hash` unique, events `(company_id, source_news_id)`.
  **Any new upsert must target an existing unique constraint** (see §11.4).
- Timezone: all persisted timestamps are UTC (`timezone=True`); scheduler runs
  in `SCHEDULER_TIMEZONE=UTC`.
- Failures are classified, never swallowed: stage statuses (`degraded ≠ success`)
  and per-company try/except with rollback keep one bad ticker from poisoning
  a whole run.

---

## 9. Configuration Reference (root `.env`)

| Group | Keys | Effect |
|---|---|---|
| App | `ENVIRONMENT`, `DEBUG` | `production` activates fail-closed secret guard + key-gated `/metrics` |
| DB/Redis | `DATABASE_URL`, `REDIS_URL`, `REDIS_CACHE_ENABLED/TTL` | per-service overrides in compose point at `db`/`redis` hostnames |
| Providers | `TWELVE_DATA_*`, `FMP_*`, `FINNHUB_*`, `FRED_*`, `MASSIVE_*`, `SEC_*` | ingestion + quotes; `TWELVE_DATA_CREDITS_PER_*` guard quotas |
| LLM | `LLM_PROVIDER/MODEL/API_KEY/BASE_URL`, `LLM_MAX_ATTEMPTS`, `LLM_RETRY_*`, `LLM_FALLBACK_MODEL` | deep analysis engine (currently `gemini`) |
| Embeddings | `EMBEDDING_PROVIDER/MODEL/DIMENSIONS/API_KEY` | RAG vectors (must match pgvector column dims) |
| Scoring | `SCORE_WEIGHT_FUNDAMENTAL=0.30`, `VALUATION=0.20`, `GROWTH=0.15`, `TECHNICAL=0.10`, `SENTIMENT=0.10`, `CATALYST=0.10`, `RISK=0.15` (subtractive) | must sum per `investment_scoring.py` contract |
| Events/anomalies | `MIN_EVENT_RELEVANCE=0.8`, `ANOMALY_MOVEMENT_THRESHOLD=80.0` + component weights | gates phantom events / anomaly noise |
| Scheduler cadence | `MARKET_DATA_UPDATE_INTERVAL_MIN`, `NEWS_PROCESSING_INTERVAL_MIN`, `ANOMALY_DETECTION_INTERVAL_MIN`, `EVENT_ANALYSIS_INTERVAL_HR`, `FUNDAMENTALS_UPDATE_INTERVAL_HR`, `SCORE_RECALCULATION_INTERVAL_HR` | **Effective** (Phase 2, Profile A) — read at scheduler boot; recreate scheduler to apply |
| Auth | `JWT_SECRET_KEY`, `AUTH_ENABLED`, `PYTHON_SERVICE_KEY` | shared by Rails + Python |
| Gateway | `CORS_ALLOWED_ORIGINS`, `SECRET_KEY_BASE`, `RAILS_MASTER_KEY`, `RAILS_BUNDLE_WITHOUT` | Rails boot + build hygiene |
| Frontend | `VITE_REFRESH_DASHBOARD_MS`, `VITE_REFRESH_ANALYSIS_JOBS_MS`, `VITE_REFRESH_ANALYSIS_DETAIL_MS` | **build args** → changing requires frontend rebuild |

Changing `.env`: compose reads `env_file` at container **creation** — restart is
not enough:

```bash
docker compose up -d --no-deps --force-recreate python worker scheduler
# gateway changes → recreate rails too; VITE_* → rebuild frontend
```

---

## 10. Operations Runbook

### 10.1 Deploy / update procedure

```bash
cd ~/intelligence-platform && git pull

# Python API code change (bind mount):
docker compose restart python

# worker / scheduler / rails code change (baked images):
docker compose up -d --build worker scheduler          # + rails if API changed

# Frontend change:
docker compose up -d --build frontend

# Full rebuild:
docker compose up -d --build
```

Rules of thumb:
- `python` = bind mount → **restart** is enough. `worker`, `scheduler`,
  `frontend`, `rails` = baked → **`--build`** required.
- Schema changes: just `git pull` + `docker compose up -d` — the one-shot
  `python-migrate` / `rails-migrate` services rerun before their dependents.
- Let running analyses finish before recreating `worker` (their jobs are
  durable but the row would be marked failed by takeover logic if interrupted).

### 10.2 Health checks

```bash
curl -s http://localhost:3000/up                      # Rails health
curl -s http://localhost:3000/health/ready            # Rails readiness
docker compose exec python curl -s localhost:8001/health/ready   # Python + DB
docker compose exec -T db pg_isready -U postgres
docker compose ps                                     # all containers Up(+healthy)
```

The readiness endpoints return `degraded` + 503 when the DB check fails —
compose healthchecks consume the Python one, so `docker compose ps` is the
first signal.

### 10.3 Data sanity snapshot (one command)

```bash
docker compose exec -T db psql -U postgres -d intelligence_stock -c "
SELECT (SELECT COUNT(*) FROM companies)                            AS companies,
       (SELECT COUNT(*) FROM news)                                 AS news,
       (SELECT COUNT(*) FROM company_news)                         AS news_links,
       (SELECT COUNT(*) FROM market_events)                        AS market_events,
       (SELECT COUNT(*) FROM anomaly_scores WHERE triggered)       AS triggered_anomalies,
       (SELECT COUNT(*) FROM alerts)                               AS alerts,
       (SELECT COUNT(*) FROM analyses WHERE status='completed')    AS completed_analyses,
       (SELECT COUNT(*) FROM work_jobs WHERE status='queued')      AS queued_jobs;"
```

### 10.4 Freshness probe (is the scheduler actually running?)

```bash
docker compose exec -T db psql -U postgres -d intelligence_stock -c "
SELECT 'news'    AS what, MAX(created_at)::text FROM news
UNION ALL SELECT 'events',       MAX(event_date)::text FROM market_events
UNION ALL SELECT 'alerts',       MAX(created_at)::text FROM alerts
UNION ALL SELECT 'prices',       MAX(timestamp)::text  FROM stock_prices
UNION ALL SELECT 'scores',       MAX(updated_at)::text FROM investment_scores;"
# Anything older than ~2× its interval ⇒ scheduler stalled → check its logs:
docker compose logs --tail=200 scheduler | grep -E 'Scheduled job|complete|error|failed'
```

### 10.5 Symptom → first checks (per feature)

| Symptom | Where to look first |
|---|---|
| Events page empty | §6.7 chain: `SELECT COUNT(*) FROM company_news` (input) → worker logs for `InvalidColumnReference`/insert errors → constraint match (§11.4) |
| "No Active Alerts" (dashboard) | API returned 200+empty ⇒ check the 3 alert sources table (§6.8); "Alerts unavailable" ⇒ backend/proxy failure |
| Dashboard sections dead | `docker compose logs python` + `rails` for the failing endpoint; per-section banner shows which one |
| Search says "not tracked yet" forever | `SELECT * FROM work_jobs WHERE kind='ingestion' ORDER BY created_at DESC` — stuck `queued`? worker alive? provider 401 in worker logs? |
| Analyses stuck `queued`/`running` | `work_jobs` rows + worker logs; takeover marks abandoned ones failed on restart |
| Quotes/prices stale | `docker compose logs scheduler | grep -i 'quota'` (TwelveData credits) |
| 401 loops / logged out | `JWT_SECRET_KEY` mismatch between rails env and token issuer; auth_sessions revoked |
| 502 from browser on slow call | gateway 30 s timeout ⇒ work was probably moved to a queue — check `work_jobs` |

### 10.6 Inspecting feature input data via docker

Event **input** = news linked to companies (before the 0.8 relevance gate):

```bash
docker compose exec -T db psql -U postgres -d intelligence_stock -c "
SELECT c.ticker, cn.relevance_score, cn.extraction_method, n.published_at, left(n.title,70)
FROM company_news cn JOIN companies c ON c.id=cn.company_id JOIN news n ON n.id=cn.news_id
ORDER BY n.published_at DESC LIMIT 15;"
# raw provider payload (what Finnhub actually returned):
docker compose exec -T db psql -U postgres -d intelligence_stock -c "
SELECT provider, retrieved_at, payload::text FROM raw_news ORDER BY retrieved_at DESC LIMIT 2;"
```

---

## 11. Known Gotchas & Guardrails

1. **Baked vs bind-mounted images** — the #1 "my fix isn't live" cause.
   `python` = bind mount (restart). `worker`/`scheduler`/`frontend`/`rails` =
   baked (`--build`). See §10.1.
2. **Scheduler cadences are config-driven** (Phase 2, D1 Profile A) — read once
   at boot from `StockConfig`; **recreate the scheduler container** after
   editing `.env` or it keeps the old cadence (§7.1). Four tasks are fixed
   (no key yet): derived metrics, macro, embeddings, backtest snapshot.
3. **News worker caps at 50 companies per run** (`process_news` `.limit(50)`).
   Growth beyond that needs batching or it will silently lag.
4. **Upserts must match real unique constraints.** See the case study below.
5. **Scheduler is single-leader** via advisory lock; two schedulers won't
   double-run, but a stalled leader blocks all periodic work — watch freshness (§10.4).
6. **`RateLimitError` aborts the remaining tickers** in a market-data run (by
   design — they defer to the next 5-min tick).
7. **Auth semantics**: refresh tokens are single-use (rotation); a stale tab
   can't clobber a newer session; auth-route 401s never trigger the login redirect.
8. **User scoping**: analyses/alerts/backtests filter by actor; system rows are
   shared. Deleting a user's rows in SQL bypasses receipts — prefer the API.
9. **Production secret guard** (`app/main.py`) refuses boot with dev defaults —
   expected behavior, not a bug.
10. **Frontend empty-state contract**: `Loading…` → `X unavailable` → `No X`.
    Don't collapse these — they distinguish "backend dead" from "no data".

### 11.4 Case study — 2026-10 events/alerts outage (hotfix `067296f`)

Migration `0015_event_dedup_company_news` replaced the `market_events` unique
constraint `(company_id, source_news_id, event_type)` → `(company_id,
source_news_id)`, but `scoring/event_detection.py` still upserted with the
3-column `ON CONFLICT` target. PostgreSQL rejects any conflict target without a
matching unique index, so **every** event insert failed
(`InvalidColumnReferenceError`), the Events page stayed empty, and
`MARKET_EVENT` alerts (which require `effective_weight ≥ 0.4` events) were
never created — while the exception was swallowed by per-company try/except in
three call sites, leaving the dashboard looking merely "empty" rather than
"broken".

Lessons:
- When a migration changes a constraint, grep for every `on_conflict_*` that
  targets those columns (`grep -rn "on_conflict" app/`).
- Swallowed exceptions need a counter/log metric — "empty page" hid a
  hard failure for weeks.
- Verify with `docker compose logs worker | grep -i InvalidColumnReference`
  and §10.3's count snapshot.

---

## 12. Testing & Validation

```bash
# Python (mocked providers, no live API calls; needs compose Redis for one test)
cd intelligence-platform-stock
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
DEBUG=false REDIS_CACHE_ENABLED=false .venv/bin/python -m pytest tests -q

# Frontend
cd intelligence-platform-frontend && npm ci && npm test && npm run build

# Read-only DB verification of framework contexts (against running compose stack)
docker compose exec -T python python scripts/verify_framework_context.py
```

- Tests use mocked providers + recorded LLM output; they never prove provider
  entitlement or factual accuracy — only behavior.
- Golden pipeline fixtures live in `tests/golden/` for deterministic replay.
- Contract reminder: framework code must never import domain code (purity
  tests enforce it); domain packs implement the `DomainModule` protocol.

---

## 13. Extending the Platform

**Add a scheduled task:** implement `async def task()` in
`app/domains/stock/workers/<name>.py`, export it in `workers/__init__.py`, add a
`_Task("Name", minutes, fn)` row in `manifest.py#get_intelligence_tasks`,
rebuild `scheduler`.

**Add an API endpoint:** new router or route in `app/domains/stock/api/`, then:
1. it is auto-mounted on both `/` (domain router) and `/internal/`;
2. add a Rails pass-through in `config/routes.rb` + `proxy_controller.rb`;
3. add the FE helper in `src/services/api.js` (envelope unwrapping is automatic).

**Add a domain:** create `app/domains/<name>/manifest.py` implementing
`DomainModule` (`app/intelligence/contracts.py`), set
`INTELLIGENCE_DOMAINS=stock,<name>`, restart. Core never changes.

**Add a table:** SQLAlchemy model + Alembic migration; update `db/schema.rb`
mirror if Rails reads it; if any upsert targets the new table, define the
unique constraint **first** and make the `ON CONFLICT` target match exactly.

---

## 14. Quick Reference — Where Things Live

| Concern | File |
|---|---|
| All public routes | `intelligence-platform-api/config/routes.rb` |
| Rails→Python proxy | `intelligence-platform-api/app/controllers/api/v1/proxy_controller.rb` |
| Python router mounting / guards | `intelligence-platform-stock/app/main.py` |
| Internal service key auth + actor | `app/core/security.py` |
| Domain wiring (tasks, routers, prompts) | `app/domains/stock/manifest.py` |
| Job queue | `app/core/jobs.py`, `app/workers/jobs.py` |
| Scheduler + leader election | `app/workers/scheduler.py` |
| Ingestion modules | `app/domains/stock/ingestion/{market,news,fundamentals,macro}.py` |
| Event/anomaly engines | `app/domains/stock/scoring/event_detection.py` |
| Analysis pipeline | `app/intelligence/pipeline.py`, `app/domains/stock/services/company_analysis.py` |
| FE API client + envelope handling | `intelligence-platform-frontend/src/services/api.js` |
| FE polling | `src/services/polling.js`, `src/config.js` |

*Generated 2026-10-20 against commit `067296f` (hotfix: market_events ON CONFLICT).*




