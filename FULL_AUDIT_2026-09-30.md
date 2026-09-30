# Full Audit — Features, Optimization, Code Quality, and UI/UX

Date: 2026-09-30 · Source commit: `e0962c7` · Revision: independent re-audit

This report replaces the earlier audit, including its incorrect registration finding. No application source or configuration was changed. Checks regenerated ignored frontend build artifacts and ordinary Rails test logs. The original report was preserved at `/tmp/FULL_AUDIT_2026-09-30.previous.md` for this session.

## 1. Assessment and evidence

The application has a substantial research workflow, useful analysis lifecycle controls, and a well-tested Python core. Its main weaknesses are at integration boundaries and in the accuracy of what the UI promises: idempotency does not survive the gateway, financial displays combine incompatible values, some filters do not mean what users expect, and background work lacks durable execution. Passing unit tests and ESLint do not establish production readiness. This report contains **48 grouped findings**: 15 feature/correctness, 12 optimization/operations, 7 code-quality, 10 UI/UX and 4 security findings.

| Area | Assessment | Main reason |
|---|---|---|
| Features | Broad implementation; correctness fixes needed | Unknown-ticker failures, alert behavior, filters, score provenance, incomplete search/pagination |
| Optimization | Reasonable frontend delivery; backend scaling risks | Synchronous Redis I/O, large-row loads, process-local jobs, polling and worker caps |
| Code quality | Strong core tests; weak boundary verification | 170 passing Python tests; no committed Rails/FE suite; migration and documentation drift |
| UI/UX | Consistent visual vocabulary; incomplete interaction coverage | Good analysis flows, but silent failures, keyboard gaps and mobile omissions |
| Release readiness | Address §9 release gates before wider use | Shared user-created alerts, unsafe defaults, public per-resource metrics and data correctness |

### Method and limits

- Reviewed Rails authentication/proxy code, routes and configuration; Python stock API endpoints, ownership helpers, analysis execution/persistence, backtesting, workers, provider/cache infrastructure, migrations and framework wiring; frontend routing, service/auth layer, page data flows, shared controls/styles; Docker/nginx/Vite configuration.
- Used targeted source tracing and isolated executable reproductions. This is **not a claim that every repository line was read**, a penetration test, or validation of financial-model accuracy.
- UI review used the current [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md). Findings below come from this application's source. No callable browser tool was available: **no live screenshots, measured contrast, keyboard walkthroughs, Lighthouse scores or real-device layout verification** were performed.
- Did not call paid providers, create real accounts, execute production analyses, modify the database, apply migrations or inspect `.env` secret values. Actual deployment settings and provider entitlements remain unverified.
- SQL findings establish query shape, not measured latency. No populated PostgreSQL `EXPLAIN ANALYZE`, load test, migration-upgrade test or live full-stack journey was performed.
- **Reproduced** means executed locally with isolated fakes/mocks or runtime checks. **Source-confirmed** means directly traceable in code. **Conditional** means deployment, data scale or a particular input is required. Reproductions are not production end-to-end tests.

### Checks executed

| Check | Result | What it establishes |
|---|---|---|
| `DEBUG=false .venv/bin/python -m pytest -q` in stock app | **170 passed in 4.51s** | Existing tests pass; 17 `test_*.py` files, not the previous report's 21 |
| `npm run lint` in frontend | **Pass** | Configured ESLint rules pass |
| `npm run build` in frontend | **Pass** | Vite builds 632 modules |
| `DEBUG=false .venv/bin/python -m alembic heads` | **0017 (head)** | One source revision head; does not verify applied DB state |
| `bundle check` in Rails app | **Pass** | Local gems available |
| Rails test-environment boot/handler inspection | **Pass** | Auth inherits the validation rescue |
| Actual Rails routes with mocked model/upstream | Registration **422**; upstream **202 becomes 200**; idempotency header **absent upstream** | Gateway and rescue behavior without real DB/upstream |
| Isolated Python probes | Broken imports; cross-user replay; nested replay body; cached empty indices; mixed scores; zero-risk substitution; misleading win rate | Details in §8 |
| Isolated Node probe of refresh module | Refresh writes credentials after simulated logout | Confirms the logout/refresh race |

The process environment initially supplied `DEBUG=release`, which Pydantic rejects as a boolean. A command-scoped `DEBUG=false` override was necessary; `.env` was not edited. This is an environment prerequisite, not a failing test under valid configuration.

Build sizes: entry JS **251.87 kB / 79.31 kB gzip**; CSS **47.00 / 8.07 kB**; lazy Backtest chunk **375.52 / 107.47 kB**. These are generated asset sizes, not measured first-paint transfer including fonts.

### Severity and priority

**High:** user isolation, materially wrong results, lost/duplicated work or broken core paths. **Medium:** functional inconsistency, accessibility barrier, operational risk or meaningful scaling cost. **Low:** polish/maintainability or a limited unused surface. **P0** is a release gate, **P1** the next corrective batch, **P2** planned hardening. Related observations are grouped rather than counted as separate defects.

## 2. Feature inventory and strengths

| Workflow | Implemented | Qualification |
|---|---|---|
| Authentication | Register/login/access and refresh tokens, user lookup, FE guard | Validation rescue works; session restore/race issues; no reset/revocation flow |
| Dashboard/market | Macro overview, indices, movers, alerts, polling | Freshness and silent-failure problems; real-time delivery not verified |
| Companies/financials | Lists, quotes, prices, statements, metrics, technicals | Unknown-ticker import failures; client search limited to fetched rows |
| News/events | Feeds, details, filters, materiality and sentiment | Filter semantics, retry behavior and stale-response protection need work |
| Analysis | Create, poll, cancel, delete, retry-as-new, evidence, saved scores | Good ownership/cancellation foundations; durable jobs/idempotency incomplete |
| Opportunities | Screening scores, personal analysis links, components, controls | Filtering and displayed score/provenance can disagree |
| Backtests | Four strategies, snapshots, benchmark, equity chart, trades | Synchronous execution; snapshot and win-rate semantics need correction |
| Alerts | Immediate creation, list/detail/read; worker-generated alerts | Shared user-written messages/read state; no user-defined trigger-rule editor |
| Search | Ticker quote and fallback company lookup | No analysis search; name lookup only searches first 100 companies |
| Portfolio | Stateless optimizer API | Portfolio UI removed; landing still promises optimization/drift monitoring |
| Framework | Generic pipeline, adapters, validation/evidence/RAG, engine flag | Legacy default; framework is selectable; live parity not verified |

Strengths to retain:

- Analysis/backtest ownership checks protect parent/child reads. Analysis cancel/delete checks management permission and locks rows; cross-user misses return 404.
- Analysis detail uses its saved score snapshot, strips internal debug blocks, and exposes request options and actionable failure metadata.
- Analysis pages guard stale responses, expose recovery actions, preserve pagination, and stop detail polling at terminal states. List polling waits for completion before scheduling the next request.
- Framework purity, contracts, deterministic fixtures, forward-return handling and cancellation regressions have useful tests. Injected services support isolated checks.
- Route splitting, independent Dashboard requests, Backtest `Promise.allSettled`, shared refresh flight, error boundary and styled confirmation controls are useful foundations.

## 3. Feature and correctness findings

### F01 — High / P1 — Unknown company/financial routes import a nonexistent module [Reproduced]

Evidence: `intelligence-platform-stock/app/domains/stock/api/companies.py:48`; `intelligence-platform-stock/app/domains/stock/api/financials.py:29`.

Both lazy ingestion paths import `app.domains.stock.api.v1.stocks`; the implementation is in `app.domains.stock.api.stocks`. A DB miss raises `ModuleNotFoundError`, instead of ingesting or returning a controlled error. Stock-quote and analysis routes use the correct module. CompanyDetail launches five requests concurrently, so financial requests can fail before quote ingestion finishes.

**Fix:** correct the import or centralize resolution. **Acceptance:** untracked ticker through company, statements, metrics and technical routes, including provider failure and concurrent first access.

### F02 — High / P0 — User-created alerts and read state are shared [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/models/alert.py:28`; `intelligence-platform-stock/app/domains/stock/api/alerts.py:20`, `:56`, `:112`.

There is no owner column or actor filtering. Any authenticated user can read and mark another user's message read. Code explicitly classifies alerts as global: this is a product/isolation design gap, not a bypass of an existing owner check.

**Fix:** distinguish private user alerts from shared system notifications; add ownership/actor checks. Shared alerts need **per-user read receipts**, not one global `is_read`. Do not blindly migrate existing user messages into public system content when authorship is unknown. **Acceptance:** two-user create/read/dismiss tests, shared receipts, and documented legacy-data policy.

### F03 — Medium / P1 — Dismissed alerts return on reload; badge becomes stale [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Alerts.jsx:21`, `:31`; `intelligence-platform-stock/app/domains/stock/api/alerts.py:58`, `:123`; `intelligence-platform-stock/app/domains/stock/schemas/alerts.py:22`.

Dismiss writes `is_read=True` and removes the local row. Reload requests all alerts because `unread_only` defaults false. Responses omit `is_read`, preventing the UI from distinguishing read entries. TopNav fetches the unread badge once per authentication change (`components/TopNav.jsx:28`), not after alert mutations.

**Fix:** explicit unread feed or All/Unread views with read state; invalidate badge/feed on mutations. **Acceptance:** dismiss, navigate away/back, reload, and verify feed/badge consistency for each user.

### F04 — High / P1 — Idempotency is broken across the public workflow [Reproduced + source-confirmed]

Evidence: `intelligence-platform-frontend/src/services/api.js:111`; `intelligence-platform-api/app/services/python_client.rb:47`; `intelligence-platform-stock/app/core/security.py:357`; `intelligence-platform-stock/app/domains/stock/api/analysis.py:218`, `:258`.

Frontend sends no key; Rails drops a caller-supplied `Idempotency-Key`. Python's process-local dictionary is keyed only by the string: no actor, route, body fingerprint or atomic reservation. Concurrent misses can create duplicate work; restarts erase entries. A user-2 request replayed user-1's analysis ID in an internal-helper probe. Current Rails header omission means this is **not demonstrated as a public cross-user exploit**.

Replay raises `HTTPException(202, detail=body)`, producing `data.detail` instead of the original `data` payload. Merely forwarding the header exposes further defects.

**Fix:** stable action key, gateway forwarding, actor/operation namespace, request fingerprint, atomic in-progress reservation, durable result and identical replay shape/status. **Acceptance:** one job for concurrent duplicates, changed-body conflict, user isolation and restart-safe replay.

### F05 — Medium / P1 — Gateway discards success status and response metadata [Reproduced]

Evidence: `intelligence-platform-api/app/controllers/api/v1/proxy_controller.rb:154`; `intelligence-platform-api/app/services/python_client.rb:45`.

Client returns only a payload and controller always renders 200. Python's 202 analysis creation and 201 resource creation are lost; request IDs/replay headers are discarded. Existing FE accepts generic 2xx, so this does not mean all create actions fail.

**Fix:** explicit upstream result with body/status/allowed headers. **Acceptance:** proxy tests for 201/202, applicable empty-body responses, errors, replay metadata, request IDs and network failures.

### F06 — High / P1 — Opportunity sector filtering occurs after LIMIT; risk profile is unused [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/investments.py:39`, `:74`, `:142`.

Query selects global top scores and limits rows before removing other sectors in Python. A sector with valid matches below global top 20 can look empty. `risk_profile` is accepted but never applied. Timestamp ties are deduplicated after limiting and can shrink the page.

**Fix:** filter before limiting; deterministic latest row per company; implement or remove/reject unsupported risk-profile filtering. **Acceptance:** matches outside global top 20 appear for the requested sector, and timestamp ties do not consume page slots.

### F07 — High / P0 — Opportunity score, filter, recommendation and provenance disagree [Reproduced]

Evidence: `intelligence-platform-stock/app/domains/stock/api/investments.py:72`, `:149`, `:156`, `:181`; `intelligence-platform-frontend/src/pages/Opportunities.jsx:38`.

Filter/order uses screening score, but displayed primary score prefers the user's analysis. Recommendation/components/version/score timestamp remain screening values. FE labels components “Deep AI Analysis” whenever an analysis ID exists. A minimum of 70 reproduced an output score of **20 with BUY**. Truthiness also changes genuine zero risk to **50**, and missing components become zero.

**Fix:** separate named screening/analysis score objects with their own provenance; define filter/order semantics; preserve zero versus missing. **Acceptance:** mixed-score fixtures verify sorting/filtering, labels, component ownership, dates, recommendations and zero/null values.

### F08 — High / P0 — Indices can stay stale or empty for 12 hours [Reproduced]

Evidence: `intelligence-platform-stock/app/domains/stock/api/market.py:34`, `:57`, `:81`; `intelligence-platform-stock/app/domains/stock/providers/base.py:183`.

`43200.0` seconds is 12 hours despite a “5 minutes” comment. All-provider failure still caches truthy `{"indices": []}`. Probe: first request made four failed calls; second made no new calls. Successful quotes can also use the provider's default 24-hour cache when enabled. A 30-second dashboard poll does not ensure fresh quotes.

**Fix:** quote-specific freshness targets, timestamps/stale metadata, short negative-cache TTL, last-known-good fallback and coalescing. Audit both cache layers. **Acceptance:** prompt outage recovery and intended expiration; UI accurately communicates freshness.

### F09 — Medium / P1 — Search uses stale URL state and incomplete coverage [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Search.jsx:14`, `:28`, `:53`; `intelligence-platform-stock/app/domains/stock/api/companies.py:20`.

On `?q=` changes, the effect sets state and immediately invokes a function closing over the old query. AAPL then MSFT through TopNav while staying on Search can execute AAPL again. Name fallback searches only the first 100 companies; backend supports no text-search parameter. Copy promises analysis search but no analysis query exists. A failed search can leave old results visible.

**Fix:** pass the intended term explicitly, URL-sync submitted search, clear/label stale results, implement server search/pagination, and narrow unsupported copy. **Acceptance:** sequential URL searches, companies beyond first page, error/empty states and back/forward.

### F10 — Medium / P1 — Event Retry and News filter semantics are incorrect [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Events.jsx:33`; `intelligence-platform-frontend/src/pages/News.jsx:41`, `:56`.

Events Retry only clears filters. On an initial unfiltered failure they are already empty, so no new request runs. News treats zero selected categories as all categories. Category/impact filtering acts on only 20 globally fetched events; ticker is sent to news but not the timeline.

**Fix:** explicit retry preserving filters, coherent all/none behavior, server-side filters before pagination, and clear scope for ticker controls. **Acceptance:** initial-outage retry and filter combinations including zero categories.

### F11 — Medium / P1 — Lists hide older records and trade detail silently truncates [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Companies.jsx:13`, `Alerts.jsx:21`, `Backtest.jsx:45`; `intelligence-platform-stock/app/domains/stock/scoring/backtest.py:1584`; `intelligence-platform-stock/app/domains/stock/api/backtest.py:151`.

Companies fetches 100, Alerts 50, runs 20 and snapshot choices 10 without page controls. Company queries lack stable ordering. Run detail embeds only the default **100 trades**; separate trade route allows a larger limit but no offset, and FE does not disclose partial detail.

**Fix:** deterministic pagination and total/truncation metadata, trade pages and snapshot search. **Acceptance:** 101 companies, 51 alerts, 21 runs, 11 snapshots and more than 100 trades remain accessible.

### F12 — High / P1 — Snapshot-pinned backtests are only partly reproducible [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/scoring/backtest.py:155`, `:247`, `:525`, `:911`, `:1178`, `:1205`.

Snapshots store prices/latest scores, not the full fundamentals/news/events promised by documentation. Score-driven strategies still query live score history. Benchmark falls back to live tables when snapshot data is insufficient. Pinned results can change after live data changes. Date-bounded queries exist; this does **not** assert that every strategy reads future prices.

**Fix:** define snapshot coverage and pin all dependencies, or explicitly mark runs partially pinned. Separate future-outcome evaluation from decision inputs. **Acceptance:** modifying live tables leaves pinned outputs unchanged or raises a clear unsupported-data error.

### F13 — High / P1 — Backtest Win Rate can contradict economic profit [Reproduced]

Evidence: `intelligence-platform-stock/app/domains/stock/scoring/backtest.py:1121`; `intelligence-platform-frontend/src/pages/Backtest.jsx:214`.

It compares unweighted average buy/sell prices per ticker, not closed-trade realized P&L. Buying 100 shares at 100 and one at 1, then selling 101 at 60, reproduces **win_rate=1.0** while return is **−39.41%**. Code calls it a proxy; UI presents a normal Win Rate.

**Fix:** quantity-aware lot/position accounting and documented denominator, or relabel/remove the proxy. **Acceptance:** partial fills/exits, multiple purchases and mixed outcomes. Document fees, slippage, adjusted-price treatment and risk-free assumptions before treating results as research-grade.

### F14 — High / P1 — Session restore is skipped; refresh can undo logout [Reproduced + source-confirmed]

Evidence: `intelligence-platform-frontend/src/services/auth.jsx:13`, `:21`, `:133`; `intelligence-platform-frontend/src/services/refresh.js:19`, `:36`.

State initializes from storage; mount effect requires `storedToken && !token`, normally impossible. Cached identity is not revalidated until protected traffic intervenes. In-flight refresh unconditionally stores credentials after completion, even after logout clears storage. A deferred-fetch probe reproduced the late write. Account switches have the same class of risk.

**Fix:** explicit startup validation and session-generation/account guard on refresh completion; invalidate/cancel on logout; synchronize context/storage. **Acceptance:** expired reload, logout/account switch during refresh and cross-tab logout.

### F15 — Medium / P2 — Product promises exceed delivered workflows [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Landing.jsx:37`; `intelligence-platform-frontend/src/App.jsx:68`; `intelligence-platform-api/config/routes.rb:19`; `intelligence-platform-stock/app/domains/stock/api/__init__.py:29`.

Landing promises portfolio optimization/drift while portfolio redirects to opportunities. Profile, Settings, Support, Documentation, Upgrade and Export are placeholders (some repeated). No custom password-reset endpoint exists despite Devise support. Alert creation inserts an immediate message, not a monitored trigger rule. Public Python domain stubs return empty/not-implemented payloads with successful status; Rails uses real internal routes.

**Fix:** align copy/navigation/status with capability; decide intended shared/internal/stub surfaces. **Acceptance:** each advertised feature maps to a working journey or explicit planned label; prioritize account recovery to launch requirements.

## 4. Optimization and operations

### O01 — High / P0 — Analysis execution and scheduler ownership are process-local [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/analysis.py:239`; `intelligence-platform-stock/app/main.py:50`; `intelligence-platform-stock/app/workers/scheduler.py:38`.

Analysis commits before BackgroundTasks executes. Abrupt termination can leave queued/active work without durable handoff/recovery. Every app process starts a scheduler; `max_instances=1` is per scheduler, not cluster-wide. Multiple processes can repeat ingestion/scores/snapshots. This is a crash-window risk, not a claim every graceful restart loses jobs.

**Fix:** durable queue/outbox, leases/heartbeats, retry policy and separately owned scheduler. A blanket startup sweeper can fail another worker's live jobs. **Acceptance:** kill after enqueue, mid-execution and before acknowledgement; recover to terminal state without duplicate paid work.

### O02 — High / P1 — Backtests and first-time ingestion do long work within HTTP requests [Source-confirmed; latency conditional]

Evidence: `intelligence-platform-stock/app/domains/stock/api/backtest.py:96`; `intelligence-platform-stock/app/domains/stock/api/stocks.py:26`; `intelligence-platform-api/app/services/python_client.rb:57`.

Backtests execute loops/evaluations before responding. Unknown-ticker GETs can ingest a year of prices plus fundamentals/news/derived metrics. Gateway operation timeout is 30 seconds. A timeout does not say whether work stopped or completed; retries can duplicate expense. CPU-heavy pandas loops share the request process.

**Fix:** async jobs/status contract, per-ticker coalescing and isolated computation. **Acceptance:** slow-provider/large-backtest cases return a job promptly and execute once. Raising the timeout alone is insufficient.

### O03 — High / P1 — Async Redis methods perform synchronous network I/O [Source-confirmed]

Evidence: `intelligence-platform-stock/app/core/redis_cache.py:72`, `:82`, `:95`, `:105`.

Async get/set directly call synchronous Redis operations; availability synchronously pings. No thread handoff exists despite the docstring. Slow Redis can block unrelated requests on the event loop. Clear uses `KEYS`; initial unavailability remains false without reconnect. Conditional on caching being enabled, which was not checked in secret-bearing deployment configuration.

**Fix:** async client or deliberate thread offload, bounded reconnect/backoff and incremental maintenance scans. **Acceptance:** delayed Redis does not stall unrelated health traffic; initial outage recovery works.

### O04 — Medium / P1 — Opportunities load analyses for the whole visible universe [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/investments.py:91`, `:102`, `:115`.

Latest-analysis aggregation is not bounded to displayed companies; outer query hydrates full Analysis records including large JSON snapshots. Restrict both stages to selected IDs and project required fields; resolve ties deterministically. Existing company/timestamp score index is present—do not duplicate it. **Acceptance:** representative query plan and memory comparison with equivalent results.

### O05 — Medium / P1 — Lean job responses still load full database rows [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/analysis.py:62`.

`select(Analysis, Company.ticker)` loads snapshots and LLM JSON before making a small response. Five-second polling multiplies transfer/deserialization. **Fix:** explicit column projection; assess actor/sort indexes with actual plans. **Acceptance:** generated SQL excludes unused JSON, while response stays identical. Lean response shape is not lean SQL.

### O06 — Medium / P1 — Worker caps can leave companies permanently stale [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/workers/market_worker.py:26`; `analysis_worker.py:33`, `:49`; `ingestion_worker.py:31`.

Recurring tasks take first batches of 50/100 without cursor/rotation. Beyond the cap, no guarantee every company refreshes. **Fix:** deterministic keyset batches or oldest-updated scheduling plus per-ticker status. **Acceptance:** all companies in a universe larger than 100 become eligible over bounded cycles.

### O07 — Medium / P1 — Metrics memory and label cardinality grow without bounds [Source-confirmed]

Evidence: `intelligence-platform-stock/app/core/observability.py:44`, `:55`, `:117`.

Each latency is appended forever. Literal paths include unique IDs; snapshots sum all retained samples. Memory/cost grows with traffic and distinct resources. **Fix:** route-template labels, bounded histograms/counters, retention and multi-process aggregation. **Acceptance:** long synthetic traffic has bounded memory. Public disclosure is S02.

### O08 — Medium / P1 — Market overview repeats unused work and misses request coalescing [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/market.py:99`, `:103`, `:159`; `intelligence-platform-frontend/src/pages/Dashboard.jsx:19`, `:27`.

Overview fetches indices/anomalies then omits them from its lean response; Dashboard separately fetches indices. Concurrent cold requests can each launch four sequential provider calls without an in-flight guard; timeout budget can exceed gateway allowance. **Fix:** remove unused work or return/use a coherent payload; coalesce misses and bound concurrency within provider quota. **Acceptance:** cold dashboard makes only intended upstream calls.

### O09 — Medium / P1 — Polling/filter changes cause avoidable work and stale overwrites [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/pages/Dashboard.jsx:40`; `News.jsx:41`; `Events.jsx:14`; `CompanyDetail.jsx:21`; `Analysis.jsx:45`; `AnalysisDetail.jsx:43`.

Dashboard interval has no in-flight guard. Polls continue in hidden tabs. News/Events fetch as ticker text changes; News also refetches feeds for local category/impact edits. Older pages lack abort/generation guards. Analysis pages provide a safer pattern already.

**Fix:** visibility-aware completion scheduling, abort/generation guards, debounced/applied filters and shared invalidation. **Acceptance:** delayed A→B responses cannot render A under B; hidden tabs pause recurring work and refresh on return.

### O10 — Medium / P2 — Remaining N+1 queries and duplicated snapshot history [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/portfolio.py:65`; `intelligence-platform-stock/app/domains/stock/scoring/backtest.py:178`, `:202`, `:475`.

Optimizer queries risk per company; snapshots query prices/scores per company; backtest price loading also loops queries. Daily snapshots duplicate historical arrays. **Fix:** measure cardinalities, batch queries, consider versioned point-in-time references and retention. **Acceptance:** query counts scale by batch, and retention does not break reproducibility.

### O11 — Medium / P2 — Hashed frontend assets lack explicit immutable caching [Source-confirmed]

Evidence: `intelligence-platform-frontend/nginx.conf:8`; generated `dist/assets/*`.

nginx has gzip, but no dedicated long-lived cache policy for hashed files. **Fix:** immutable fingerprinted assets, revalidatable HTML, and 404 rather than SPA HTML for missing assets. **Acceptance:** verify HTML/current/missing asset headers and deploy refresh. Previous claim of “830 KB every revisit” was unmeasured and is withdrawn.

### O12 — Medium / P1 — Runtime/readiness configuration is incomplete for production [Source-confirmed]

Evidence: `docker-compose.yml:71`, `:103`; `intelligence-platform-stock/app/domains/stock/api/internal_router.py:51`; `intelligence-platform-stock/app/main.py:160`.

Supplied compose uses reload/source mounts, publishes DB/Redis ports, and starts Rails when Python is only started. No Python/Rails container healthchecks. Readiness returns 200 even when database is degraded. Do not assume this compose exactly represents deployed production.

**Fix:** explicit dev/prod profiles, health probes, degraded readiness 503, intentional network/TLS boundary. **Acceptance:** cold dependency startup and unavailable-database readiness tested.

## 5. Code quality and architecture

### Q01 — High / P1 — Tests miss application boundaries [Source-confirmed]

Evidence: `intelligence-platform-stock/tests/`; `intelligence-platform-api/Gemfile`; `intelligence-platform-frontend/package.json`.

170 tests are valuable but many call helpers/services with fakes; they do not prove PostgreSQL constraints, gateway behavior or browser interaction. No committed Rails test/spec suite or FE runner was found; no tracked GitHub Actions workflow. This does not establish a coverage percentage or rule out external CI.

**Fix:** regressions for reproduced failures, then real DB/gateway and small browser suites. **Acceptance:** two-user isolation, duplicate creation, unknown ticker, refresh/logout, filters, failed backtest, keyboard/mobile paths run automatically.

### Q02 — Medium / P1 — Migration startup can falsely certify or race schema changes [Source-confirmed; outcome conditional]

Evidence: `intelligence-platform-stock/scripts/migrate.sh:30`, `:58`; `docker-compose.yml:32`, `:74`; `intelligence-platform-api/db/migrate/20260810030000_add_user_id_to_analyses_and_backtest_runs.rb:9`.

If companies exists without Alembic history, script stamps head without verifying later changes. Rails/Python migrators can run concurrently; Rails alters Python-owned tables without waiting for Python migrations. Existence checks are not atomic DDL synchronization.

**Fix:** verified baseline/reconciliation, one migration owner per table, serial dependencies. **Acceptance:** clean and incomplete legacy schemas migrate correctly, reruns are safe, and history matches schema. Do not run destructive validation against production.

### Q03 — Medium / P1 — Input validation does not consistently protect DB/compute boundaries [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/companies.py:22`; `api/alerts.py:59`; `schemas/alerts.py:12`; `schemas/backtest.py:29`; `scoring/backtest.py:521`.

Many limits omit positive lower bounds and offsets allow negative values. Alerts accept unconstrained type/severity/message strings despite database limits. Backtest strategy is validated but parameters is arbitrary: `rebalance_days=0` reaches modulo operations. Date-range/ticker-count/string limits are incomplete.

**Fix:** shared pagination, model-aligned lengths/enums, typed per-strategy parameters and resource bounds. **Acceptance:** invalid inputs produce stable 4xx before writes or costly processing.

### Q04 — Medium / P1 — Error handling masks faults and has transaction-recovery gaps [Source-confirmed]

Evidence: `intelligence-platform-stock/app/domains/stock/api/stocks.py:47`, `:96`; `api/analysis.py:191`; `scoring/backtest.py:451`; `api/backtest.py:114`.

Auto-ingestion turns broad failures into None/404 and silently skips stages. Analysis failure-state persistence can itself fail silently. Backtest catch commits on the same session without first recovering a failed transaction, so DB exceptions can prevent promised failure persistence. Public backtest error text includes raw exception details.

**Fix:** typed failures, structured stage warnings, rollback and reliable separate failure persistence, safe public errors with correlation IDs. **Acceptance:** invalid ticker/provider outage/DB failure/failure-recording failure are distinguishable and observable.

### Q05 — Medium / P2 — Envelope middleware relies on internal response representation [Source-confirmed]

Evidence: `intelligence-platform-stock/app/core/response_envelope.py:86`.

Middleware consumes `response.__dict__["body_iterator"]`, buffers bytes, parses JSON and serializes a replacement. On parse failure, returning original response does not restore the consumed iterator. Performance cost is plausible but unmeasured; “will break on upgrades” is too absolute.

**Fix:** explicit envelope boundary or supported ASGI handling with bounded buffering. **Acceptance:** success/list/error/validation/empty/malformed/streaming behavior and profiling of large responses.

### Q06 — Medium / P2 — Documentation/configuration drift hides executable architecture [Source-confirmed]

Evidence: `intelligence-platform-stock/app/intelligence/pipeline.py:18`; `intelligence-platform-stock/app/domains/stock/services/company_analysis.py:376`, `:496`; `intelligence-platform-stock/app/domains/stock/pipeline_factory.py:22`; `README.md:8`.

Comments claim pipeline is not instantiated in production, but shared execution selects a wired framework factory. Legacy is the default; deployed choice unverified. README still quotes 110 tests/old audit links. Cache/snapshot comments also drift. No configured Python lint/type gate found; `google-genai>=1.0.0` is open-ended among pinned direct dependencies.

**Fix:** document default/selectable paths and readiness gates, effective non-secret diagnostics, gradual lint/type checks, reproducible dependency lock. **Acceptance:** examples/imports/config checked in CI; live parity never inferred solely from fake-driven tests.

### Q07 — Low / P2 — Duplicated/unused interfaces increase maintenance risk [Source-confirmed]

Evidence: `intelligence-platform-frontend/src/services/auth.jsx:49`, `:91`; `services/api.js:20`, `:59`; `intelligence-platform-api/Gemfile:17`; `intelligence-platform-api/app/controllers/application_controller.rb:5`.

Auth duplicates login/register token/profile code. Unused health helpers prepend `/api/v1` although Rails health routes are root-level. Spreading options after headers makes future `options.headers` replace merged bearer/content headers—relevant when adding idempotency. Pundit is included/rescued but no policy calls found; Kaminari has no pagination calls.

**Fix:** tested shared primitives; correct/remove unused helpers; preserve merged headers; remove dependencies only after usage checks. **Acceptance:** custom headers retain auth and both auth paths share tested behavior.

## 6. UI/UX findings

Source-based findings grouped by file/flow. Dark-only design, absence of skeletons and absence of virtualization are not automatically defects; actual impact should drive priority.

### U01 — High / P1 — Failure/missing data can resemble valid results

- `intelligence-platform-frontend/src/pages/Dashboard.jsx:19` — failures clear data without error/Retry. `:50` substitutes a 45% VIX gauge when VIX is missing.
- `intelligence-platform-frontend/src/pages/CompanyDetail.jsx:26` — allSettled returns rejected results normally; surrounding catch does not report ordinary API failures. All five can fail without useful error feedback.
- `intelligence-platform-frontend/src/pages/News.jsx:65` — missing VIX can become a moderate/high classification through null/undefined coercion instead of an unknown state.

**Fix/acceptance:** loading/empty/partial-error/stale states, actionable Retry and no invented gauge/classification. Test partial and total outages.

### U02 — High / P1 — Mobile lacks full navigation and sign-out

- `intelligence-platform-frontend/src/components/TopNav.jsx:45` — user menu/header hidden below md.
- `intelligence-platform-frontend/src/components/Sidebar.jsx:22` — full navigation hidden below md.
- `intelligence-platform-frontend/src/components/MobileNav.jsx:6` — only Home/Markets/Opportunities/AI/Alerts, with no full/account menu.

Contextual page links exist, but no equivalent full navigation or layout sign-out. **Fix/acceptance:** More/account drawer or menu; every supported route and sign-out reachable at narrow width without typing URLs.

### U03 — Medium / P1 — Confirmation dialog lacks complete focus lifecycle

- `intelligence-platform-frontend/src/components/ConfirmDialog.jsx:18` — initial Cancel focus/Escape support, but no trap/restoration/background inertness.
- `intelligence-platform-frontend/src/components/ConfirmDialog.jsx:22`, `:33` — Escape/backdrop cancel even when busy buttons are disabled.

**Fix/acceptance:** reliable dialog primitive/native dialog behavior; contained Tab/Shift+Tab, restored trigger focus, unavailable background and coherent busy-dismiss semantics.

### U04 — Medium / P1 — Important navigation/actions are mouse-only or invisible

- `intelligence-platform-frontend/src/components/TopNav.jsx:48` — brand anchor has click handler but no href.
- `intelligence-platform-frontend/src/pages/Companies.jsx:83`, `Events.jsx:105`, `Search.jsx:191` — clickable rows without ordinary navigation links/keyboard activation.
- `intelligence-platform-frontend/src/pages/Alerts.jsx:211` — Dismiss hidden by opacity with hover-only reveal; focus can land on an invisible action.

**Fix/acceptance:** links for navigation, visible/focus-revealed actions, adequate touch targets; keyboard and no-hover checks. Opportunity rows already have keyboard handling.

### U05 — Medium / P1 — Form labels are often not associated with controls

- `intelligence-platform-frontend/src/pages/Login.jsx:68`, `Register.jsx:62` — detached labels, no input IDs/htmlFor; no explicit name/autocomplete semantics.
- `intelligence-platform-frontend/src/pages/Alerts.jsx:99`, `Backtest.jsx:138` — detached labels in create forms.
- `intelligence-platform-frontend/src/components/TopNav.jsx:60`; `pages/Search.jsx:77`; `pages/Events.jsx:50` — search/filter controls rely on placeholders.

**Fix/acceptance:** label association, password-manager semantics, described/announced errors and first-error focus; verify accessible names and autofill.

### U06 — Medium / P2 — Navigation state is not consistently shareable/recoverable

- `intelligence-platform-frontend/src/App.jsx:48` — no catch-all not-found route.
- `intelligence-platform-frontend/src/pages/Backtest.jsx:28` — selected run only in local state; refresh/share loses selection.
- `intelligence-platform-frontend/src/components/RequireAuth.jsx:12` — return destination drops search/hash.
- `intelligence-platform-frontend/index.html:7` — static title; no route-specific title updates found.

**Fix/acceptance:** route-backed details/filters, complete return destination, not-found page, meaningful titles and route focus behavior; check back/forward/copied URLs.

### U07 — Medium / P2 — Some lists show empty states before fetching completes

- `intelligence-platform-frontend/src/pages/Alerts.jsx:8`, `Companies.jsx:8`, `News.jsx:27` — initial empty arrays without distinct initial loading state.
- `intelligence-platform-frontend/src/pages/Companies.jsx:102` — filtered zero results say no companies tracked.
- `intelligence-platform-frontend/src/pages/Alerts.jsx:227` — “System monitoring is running” inferred from an empty list, without worker-health check.

**Fix/acceptance:** initial loading, filter-aware empty copy and evidence-backed health claims. Skeletons optional; truthful states required.

### U08 — Medium / P2 — Layout lacks skip/motion/safe-area accommodations

- `intelligence-platform-frontend/src/components/Layout.jsx:13` — no skip-to-main; mobile retains pt-16 despite hidden header.
- `intelligence-platform-frontend/src/components/MobileNav.jsx:20` — no safe-area padding on fixed bottom bar.
- `intelligence-platform-frontend/src/components/StatusChip.jsx:6`, `Toast.jsx:35`; `src/index.css:114` — pulse/animation/broad transitions without project reduced-motion treatment.

**Fix/acceptance:** skip link, responsive spacing, safe-area padding and motion variants; verify keyboard, notched devices and motion preference.

### U09 — Medium / P2 — Menu/long-content behavior is incomplete

- `intelligence-platform-frontend/src/components/TopNav.jsx:91` — menu lacks expanded relationship and explicit Escape/focus lifecycle.
- `intelligence-platform-frontend/src/pages/Alerts.jsx:206` — truncated messages have no full-detail/expand affordance.
- `intelligence-platform-frontend/src/components/Toast.jsx:29` — fixed container lacks explicit narrow-screen width/long-string wrapping strategy.

**Fix/acceptance:** accessible disclosure/menu, full-message view, bounded wrapping and decorative-icon semantics; test long names/messages and keyboard dismissal.

### U10 — Low / P2 — Theme/typography refinements need measured validation

- `intelligence-platform-frontend/index.html:2`; `src/index.css:73` — dark palette but no native color-scheme/theme-color metadata.
- `intelligence-platform-frontend/src/index.css:123` — monospace data class is not a shared units/precision/missing-value formatting policy.
- `intelligence-platform-frontend/index.html:10` — fonts have preconnect/swap; actual stylesheet/font cost was not measured.

Keep dark-only if intentional. Add native theme metadata/consistent formatting, then measure contrast/zoom/long content. Do not prioritize font replacement or virtualization over confirmed correctness/accessibility failures.

## 7. Cross-cutting security

### S01 — High / P0 — Missing/default configuration enables privileged access [Source-confirmed; exposure conditional]

Evidence: `intelligence-platform-stock/app/core/security.py:236`, `:274`; `intelligence-platform-api/config/initializers/gateway.rb:7`; `docker-compose.yml:93`.

Python permits requests without configured service keys; missing role defaults SYSTEM. Rails defaults auth off outside compose and has known JWT/service-key fallbacks. Compose defaults Rails auth on but retains known keys. Python is container-network-only in supplied compose; no claim it is publicly deployed. Known JWT defaults remain a public gateway risk if used.

**Fix:** explicit environment mode, fail-closed production secrets, valid forwarded identity, separately authenticated system identity. **Acceptance:** boot refuses unsafe secrets; missing/invalid identity never becomes SYSTEM. Do not print actual secret values.

### S02 — High / P0 — Public metrics disclose literal resource paths [Source-confirmed]

Evidence: `intelligence-platform-api/config/routes.rb:16`; `intelligence-platform-api/app/controllers/public_controller.rb:5`; `intelligence-platform-stock/app/core/observability.py:117`; `intelligence-platform-frontend/nginx.conf:27`.

Public controller exposes metrics. Python records literal paths including analysis IDs and returns them as keys. Anyone reaching that endpoint can learn accessed identifiers/activity. This does not bypass owner checks or expose full analysis bodies, but weakens intended non-disclosure of existence.

**Fix:** private/authenticated metrics and normalized labels. **Acceptance:** unauthenticated access denied and no resource/user IDs in telemetry; also addresses O07 cardinality.

### S03 — High / P1 — No effective inbound abuse limiting [Source-confirmed]

Evidence: `intelligence-platform-stock/app/core/rate_limit.py:23`, `:85`; `intelligence-platform-api/app/controllers/api/v1/auth_controller.rb:15`; `intelligence-platform-stock/app/domains/stock/api/analysis.py:203`.

Python limiter exists but no route/middleware wiring found, and defaults disabled. No inbound Rails throttle found. Outbound provider limits exist but do not protect auth attempts or authenticated paid-work requests. No per-user work/concurrency budget enforcement found at these boundaries.

**Fix:** public auth throttles, shared per-user work/concurrency limits and safe forwarded-IP handling. **Acceptance:** multiple workers enforce one budget with clear retry responses.

### S04 — Medium / P1 — Refresh lifecycle and frontend hardening are incomplete [Source-confirmed]

Evidence: `intelligence-platform-api/app/services/jwt_service.rb:16`; `intelligence-platform-frontend/src/services/token.js:1`; `intelligence-platform-frontend/nginx.conf:1`.

Stateless refresh tokens default to seven days; new pairs do not invalidate old refresh tokens. Logout clears localStorage only; same-origin scripts can read it. nginx defines no CSP/content/framing headers. No injection exploit demonstrated; outer infrastructure may add headers.

**Fix:** explicit rotation/revocation/reuse policy, F14 correction and tested header/CSP policy. Cookies are an architectural option requiring CSRF design, not a mechanical replacement. **Acceptance:** logout/revocation and old-refresh reuse behavior tested.

## 8. Reproductions and corrections

### Isolated runtime results

| Probe | Setup | Observed |
|---|---|---|
| Invalid registration | Actual Rails route; fake User raises RecordInvalid | `422 {"detail":"Password is too short"}` |
| Gateway status/header | Actual route; fake upstream 202; caller key supplied | Public 200; outbound Idempotency-Key absent |
| Unknown ticker | Fake DB returns no company | Both company/financial paths raise missing api.v1 module |
| Cross-user replay | Store user-1 response; check key with user-2 identity | Internal helper returns user-1 analysis ID |
| Replay payload | FastAPI app with actual envelope middleware/202 exception | `data` is `{"detail":{"analysis_id":"audit","status":"queued"}}` |
| Failed index cache | Four provider failures; call twice | Empty both times; four total calls; TTL 43200 |
| Opportunity mismatch | Screening 80/BUY, analysis 20, risk 0, min 70 | Score 20, BUY, risk 50 |
| Win-rate proxy | Buy 100×100 and 1×1, sell 101×60 | Win rate 1.0; return −0.394061 |
| Refresh after logout | Deferred fetch resolves after clearing fake storage | Credentials written again |

No real upstream calls or DB writes. These demonstrate control flow/arithmetic, not live availability. Rails probe is session-local `/tmp/intelligence-audit-gateway.rb`, not a committed test suite.

### Withdrawn/corrected previous claims

1. **Registration 500:** withdrawn; ApplicationController rescues validation and runtime route probe returned 422. Add coverage, not a duplicate P0 rescue.
2. **Eight-character server minimum:** FE requires eight; Devise permits six (`intelligence-platform-api/config/initializers/devise.rb:184`). Align policy; seven characters is not equally invalid at both boundaries.
3. **Rate limiter unimplemented:** implemented but unwired/disabled; outbound limits also exist.
4. **Missing composite score index:** migration `0001_initial.py:390` creates it. Live DB/plans still need checking.
5. **Framework entirely unwired:** shared service selects wired framework factory; legacy is default, not the only path.
6. **Only Dashboard hides errors:** CompanyDetail also hides ordinary request failures.
7. **21 Python test files:** actual `test_*.py` count 17; 170 tests passed.
8. **Universal cleanup/strong accessibility:** older pages lack response guards and several essential interactions/labels are incomplete.
9. **Stale ignored bytecode as material defect:** excluded. Bytecode alone does not prove applied migration drift.
10. **Measured middleware/revisit performance:** not established; this audit specifies measurements instead of invented latency/transfer numbers.
11. **Remove Devise modules to solve missing recovery:** removal does not deliver account recovery; implement the chosen product behavior.
12. **Blanket startup reaper:** unsafe with live workers; use leases/heartbeats.

## 9. Remediation plan and release gates

Effort ranges include focused tests and assume stack familiarity/integration environment. They are planning estimates, not commitments. Queue/session/schema work is not universally a half-day fix.

| Priority | Package | Findings | Estimate | Gate |
|---|---|---|---|---|
| P0 | Secret/telemetry boundaries | S01, S02, O07 part | 1–2 days | Unsafe boot refused; no public resource-level telemetry |
| P0 | Private alerts/shared receipts | F02, F03 | 1–3 days | Two-user isolation/read tests; legacy-data policy |
| P0 | Accurate financial displays | F07, F08; schedule F13 promptly | 1–3 days | Coherent scores/provenance/zero values and freshness |
| P0 | Durable work before scaling/restart-sensitive use | O01, F04 foundation | 3–7 days | Crash recovery, one job/action, scheduler ownership |
| P1 | Broken paths/filters/search | F01, F06, F09, F10 | 1–3 days | Regression fixtures at the actual boundaries |
| P1 | Gateway contract/throttles | F04, F05, Q03, S03 | 2–4 days | Preserved contract, atomic scoped replay, limits |
| P1 | Auth lifecycle | F14, S04, password alignment | 2–4 days | Logout/account switching cannot be overwritten |
| P1 | Backtest truthfulness/execution | F12, F13, O02, Q04 | 3–6 days | Reproducibility, quantity-aware outcomes, durable work |
| P1 | Backend cost/migration/runtime | O03–O08, O12, Q02 | 2–5 days | Nonblocking cache, bounded metrics, full-universe refresh |
| P1 | Core UX/accessibility/paging | U01–U05, F11 | 2–4 days | Useful errors, complete mobile nav, focus/labels, reachable records |
| P1/P2 | Test infrastructure | Q01, Q06 | 2–4 days initially | Automated regressions plus real DB/service checks |
| P2 | Delivery/polish/cleanup | F15, O09–O11, Q05–Q07, U06–U10 | Stage afterward | Measured improvements and browser-verified behavior |

Required validation before calling remediation complete:

- Clean and legacy DB migration runs, not just source-head inspection.
- Real PostgreSQL tests for ownership, paging, timestamp ties, invalid inputs and concurrent job reservation.
- Rails→Python tests of statuses, headers, errors and idempotency.
- Two-user browser journeys for alerts/analysis and session expiry/logout/account switches.
- Desktop keyboard/mobile checks, accessible names, dialog focus, reduced motion and error/empty states.
- Representative query plans/load tests; Redis outage/delay and abrupt worker termination.
- Controlled provider smoke tests with budget/freshness expectations when an integration environment is available.

## 10. Suggested implementation sequence

Start with certain regressions—F01 imports, F03 unread-feed behavior, F06 sector filtering, F07 zero handling, F08 cache freshness and F10 retry—while designing ownership/job contracts. Correct score provenance as a coherent API/UI change, not merely a label patch. Add regression tests with each fix, then deliver durable shared-state/session work and verify across processes. Reserve visual polish/dependency cleanup until core flows present accurate, recoverable results.

## 11. Remediation log (applied 2026-09-30, after this report)

Fixes applied to the working tree (uncommitted) following this report's own §10 sequence. **Verification:** `pytest` **177 passed** (172 existing + 5 new regressions), `eslint` clean, `vite build` green (entry 252.05 kB / 79.37 kB gzip — unchanged), `py_compile` on every edited module, `ruby -c` on edited Ruby files, plus a live boot-guard check.

| Audit ID | Status | Change |
|---|---|---|
| **F01** (High) | ✅ Fixed | `companies.py` / `financials.py` auto-ingest now import the existing `app.domains.stock.api.stocks`; the nonexistent `api.v1.stocks` path is gone. Locked by a source-scan regression test. |
| **F02** (P0) | 🟡 Partial | Alerts carry `user_id`: Alembic `0018_user_scoped_alerts` + idempotent Rails mirror `20260930000000`; `create/list/get/mark-read` are actor-scoped (`visible_to_actor`/`owns_row`), cross-user dismiss returns the same 404, `can_manage` gates the FE action. **Remaining:** per-user read receipts for shared system alerts + legacy-data policy (interim: system rows read-only for regular users, admins may dismiss). |
| **F03** (P1) | ✅ Fixed | `AlertResponse` exposes `is_read`; feed has an explicit **Unread/All** view (unread default) so dismissed rows no longer reappear on reload; new `services/alertsSignal.js` invalidates the TopNav badge on create/dismiss instead of once per session. |
| **F06** (High) | ✅ Fixed | Sector filtering moved into SQL **before** LIMIT; latest-score selection is a deterministic one-row-per-company subquery (max ts, tie-broken by id) so ties can't consume page slots; unapplied `risk_profile` param **removed** (documented) rather than silently ignored. |
| **F07** (P0) | ✅ Fixed | Screening and analysis scores are separate provenances: `score`/`recommendation`/`components`/`scoring_*` all come from the screening row that is also filtered/ordered; the deep analysis reports its own `analysis_score`. `risk_score` and component values preserve **null** instead of fabricating `50`/`0`; FE labels the breakdown "Screening model", shows the analysis score in its own row, and renders missing risk neutrally instead of green. |
| **F08** (P0) | ✅ Fixed | Indices cache TTL `43200.0 → 300.0` s; cache populated only on success, failures use a 30 s negative cache and serve **last-known-good**, so an all-provider outage no longer pins an empty dashboard for hours. |
| **F10** (P1) | ✅ Fixed | Events Retry re-runs the current query (previously only cleared filters — a no-op on initial failure). News treats zero selected categories as **none**, not "all", and says so in the header. |
| **U01** (High) | 🟡 Partial | Dashboard surfaces per-section failures with a Retry banner (and drops the no-op `setTimeout`); invented 45% VIX gauge fallback removed; News reports VIX as **unknown** instead of coercing `null < 30` into "moderate". **Remaining:** CompanyDetail still hides ordinary request failures. |
| **S01** (P0) | 🟡 Partial | Python + Rails refuse to boot with unset/known-default secrets unless `ENVIRONMENT=development` (verified live); a missing/blank `X-User-Role` no longer defaults to **SYSTEM** — falls back to `USER` (tests updated). **Remaining:** separately authenticated system identity. |
| **S02** (P0) | 🟡 Partial | Metrics labels are route-templated (`normalize_endpoint`) so telemetry records no analysis UUIDs/numeric ids (also caps the O07 cardinality growth). **Remaining:** the public `/metrics` route still needs to be private/authenticated. |
| **O04** (P1) | ✅ Fixed | Latest-analysis aggregation bounded to the displayed companies (`company_id IN (...)`), previously an unbounded scan. |
| **O11** (P2) | ✅ Fixed | nginx serves `/assets/*` with `expires 1y` + `immutable` and **404s missing hashed files**; `index.html` explicitly revalidates so deploys still take effect. |
| **Q07** (Low) | 🟡 Partial | `api.js` spreads `options` **before** the merged `headers`, so a future `Idempotency-Key` can't silently drop the Authorization header. **Remaining:** auth.jsx duplication, unused helpers/gems. |

### Correction to the previous report (retained for the record)
- The earlier "registration 500" finding was **withdrawn as incorrect** by this report and is confirmed wrong: `ApplicationController` already rescues `ActiveRecord::RecordInvalid` → 422. The duplicate rescue added during that earlier pass has been **reverted**; only the route doc comment now documents the 422 path.

### Not verified in this environment (explicitly open)
- **No database was running**, so the F02/F03/F06/F07/F08 fixes are verified by unit/regression tests, SQL-shape review and source tracing — **not** by PostgreSQL row-level or `EXPLAIN` checks. The §9 validation list (real-DB two-user journeys, migration upgrade test, query plans) still applies.
- The local macOS venv has a broken scipy wheel (`dlopen ... _propack/_spropack`), so the stock scoring chain and the `/internal` router cannot be imported outside Docker here; pre-existing and unrelated to these changes.
- Alembic revision-id note: the deleted migration sources also used `0018`/`0020`/`0021`. Fresh databases are unaffected; if a local DB recorded a deleted revision, inspect `alembic current` and the actual schema, take a backup, and reconcile its migration history before upgrading. Do not blindly stamp `0017`: that can conceal schema differences.

### Remediation batch 2 — gateway contract + accessibility

| Audit ID | Status | Change |
|---|---|---|
| **F04** (P1) | 🟡 Partial | FE sends an `Idempotency-Key` on analysis create; Rails forwards **only** that header; Python namespaces the key by *(actor, method, path, body-fingerprint)* — closing the reproduced cross-user replay — and replays return the **original status + payload** (`IdempotencyReplay` + exception handler) instead of an error envelope. **Remaining:** durable/shared (Redis) replay, atomic in-progress reservation, changed-body conflict signalling. |
| **F05** (P1) | ✅ Fixed | `PythonClient` now returns `Result(status:, body:, headers:)`; `ProxyController` renders the upstream status (201/202/204, with 204 → `head :no_content`) and relays `Idempotency-Key`/`Idempotency-Replayed`/`X-Request-Id` instead of flattening everything to 200. |
| **S02** (P0, remainder) | ✅ Fixed | `/metrics` is **no longer proxied by nginx**, and both Rails (non-development) and Python (non-development) require the internal service key — so traffic telemetry is not internet-reachable. |
| **U01** (High, remainder) | ✅ Fixed | CompanyDetail reports *which* of its five parallel requests failed (previously five failures rendered as silently empty sections) and offers Retry. |
| **U02** (High) | ✅ Fixed | MobileNav gains a **More** sheet with the remaining routes plus **Sign Out**; safe-area padding on the bar and sheet. |
| **U03** (Medium) | ✅ Fixed | ConfirmDialog contains Tab/Shift+Tab, restores focus to the trigger on close, blocks Escape/backdrop while `busy`, and exposes `aria-busy`. |
| **U05** (Medium, auth flows) | ✅ Fixed | Login/Register controls now have `id` + `htmlFor`, `name` and `autoComplete` (`email`, `current-password`, `new-password`, `name`) so password managers and screen readers work. **Remaining:** Alerts/Backtest create forms and the placeholder-only filter controls. |

**Batch 2 verification:** `pytest` **179 passed** (2 new idempotency tests inside `tests/test_audit_fix_regressions.py`, 7 total there), ESLint clean, `vite build` green, `ruby -c` on all three edited Ruby files, and a standalone Ruby simulation of the gateway proving: upstream URL built correctly, `Idempotency-Key` forwarded only when supplied, service key preserved, **status 202 preserved**, body unwrapped, allow-listed headers relayed, and the legacy body-only helper still working.

### Remediation batch 3 — inbound throttling, truthful UI, routing & accessibility

| Audit ID | Status | Change |
|---|---|---|
| **S03** (P1) | 🟡 Partial | New `app/core/rate_limit_middleware.py` mounted **inside** the envelope (429 gets the standard `{"error": ...}` shape with `Retry-After` preserved). Checks `POST …/analysis/company` and `…/portfolio/optimize` on **both** the public and internal mounts *before* any work runs; `RATE_LIMIT_ENABLED` now defaults **true** (`.env.example` documents it); `get_client_key` prefers the gateway's `X-User-Id` so budgets are **per user**, not one shared container IP. **Remaining:** the sliding window is per-process (N workers = N budgets) — shared Redis budget still open; Rails `/auth/*` still needs rack-attack. |
| **O07** (P1) | ✅ Fixed (verified in tree) | Latency metrics are `[sum, count]` accumulators instead of ever-growing lists; labels are route-templated (`normalize_endpoint` + `scope["route"].path`, unmatched → `"unmatched"`); `snapshot()` no longer sums retained samples. Label cardinality and memory are bounded. |
| **U06** (P2) | ✅ Fixed | `path="*"` catch-all renders a real **NotFound** page (unknown URLs previously rendered blank); new `PageTitle` component sets per-route `document.title` (`Dashboard — Market Intelligence`, …). **Remaining:** Backtest selected-run still lives only in local state. |
| **U08** (P2) | 🟡 Partial | Skip-to-main link (first tab stop, `focus:not-sr-only`) + focusable `<main id="main">`; global `@media (prefers-reduced-motion: reduce)` collapses every animation/transition; safe-area padding already landed in batch 2. **Remaining:** mobile `pt-16` while the header is hidden. |
| **F15** (P2) | ✅ Fixed (copy) | Landing no longer promises portfolio optimization/drift — hero, feature card ("Backtesting & Screening") and CTA now describe **delivered** journeys (backtesting, opportunity screening). Password-reset delivery remains its own open item. |
| **S04** (P1) | 🟡 Partial | nginx sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` on HTML **and** hashed assets (repeated per-location because nginx `add_header` inheritance is replaced, not merged). **Remaining:** CSP deferred until browser-verifiable; server-side refresh-token rotation. |

**Batch 3 verification:** `pytest` **183 passed** (+4 S03 tests: path scoping, 429 + `Retry-After`, disabled-flag escape hatch, `X-User-Id` key preference); live app assertion of the middleware stack (`ResponseEnvelope → RateLimit → RequestID → CORS`); ESLint clean; `vite build` green (entry 255.38 kB gzip 80.46 kB).

### Concurrent batch landed in this working tree (verified present)

A parallel stream implemented several items from §9 while this batch was in progress; all verified by inspection and covered by the green suite:

- **O01 + O02 (durable work)** — `app/core/jobs.py` PostgreSQL outbox (`reserve_job`: atomic `INSERT … ON CONFLICT`, fingerprint → 409 on body change, replay → original 202) + `app/workers/jobs.py` standalone worker (advisory-lock lease, abandoned-`running` → explicit fail rather than silent replay) + compose `worker` service. Backtest POST is now **202 async**; API process no longer executes pandas loops inline.
- **F02 remainder (per-user receipts)** — `alert_reads` + `legacy_private` (migration 0019) with per-viewer `_read` receipts: shared notifications are dismissed independently per user; legacy ownerless rows quarantined with `legacy_private=true` (visible only to admins until ownership is reconciled).
- **O03** — `redis_cache.py` now uses `redis.asyncio` (no sync ping in `available`, no `KEYS` in clear).
- **O12** — compose healthchecks (python `health/ready`, rails gated `service_healthy`), readiness returns **503** when degraded (public + internal), `uvicorn --reload` removed.
- **F14 + password alignment** — auth/session rewrite (`SESSION_EVENT` generation, cross-tab `storage` sync, loading/error/retry in `RequireAuth`, full return path incl. query/hash); Devise `password_length` 6→8 matching the FE.
- **Q02** — `migrate.sh` now **refuses** to blind-stamp an unverified schema.
- **F09/O06 partial** — server-side company `q` search with escaping + deterministic ordering; market worker orders by id (full keyset rotation still open).


### Remediation batch 4 — backtest reproducibility disclosure (F12)

**F12** (High) — 🟡 **Fixed via the audit's "explicitly mark runs" option** (full score-history pinning remains a designed follow-up):

- `BacktestRun.snapshot_coverage` (JSONB) + Alembic **0020** (idempotent, single head) records `{mode, snapshot_id, snapshot_as_of, pinned, live}` per run.
- `compute_snapshot_coverage()` (pure, tested) classifies **decision inputs only**: prices always pinned when a snapshot is used (or the run fails fast — verified no silent price fallback), `benchmark` pinned or live depending on where `_compare_benchmark` actually sourced it (the function now returns its source: `"snapshot" | "live" | "none"`), and `score_history` flagged **live** for `score_threshold`/`portfolio_optimizer` — the reproduced core of F12 (snapshots capture only the *latest* score per ticker, so those strategies read live, date-bounded score history even when pinned).
- API: `BacktestRunResponse.snapshot_coverage` → propagated to list + detail automatically (`model_validate`); runs predating the field are `null`.
- FE (Backtest detail): three-state disclosure — **"Fully pinned"** (tertiary banner), **"Partially pinned"** (secondary banner naming exactly which inputs are live and that re-runs can differ), and a subtle **"Data pinning: none"** line for unpinned runs. Evaluation phases are documented as outcome-measurement (live by design), not decision inputs.

**Batch 4 verification:** `pytest` **186 passed** (+3 F12 tests covering unpinned / partially-pinned / fully-pinned / live-benchmark-fallback / no-benchmark classification), `alembic heads → 0020 (head)`, ESLint clean, `vite build` green.

**Honest limits:** this is disclosure, not full pinning — extending snapshots to capture score history (making score-driven runs fully pinned) is still open work; the migration was not applied to a live database in this environment; legacy runs show no disclosure until re-executed.

**Updated still-open (supersedes the list above):** P0 — shared Redis rate-limit budget + Rails auth throttle (S03 remainder). P1 — O05 lean job projection, O08/O09 coalescing + visibility-aware polling, O10 N+1 batches, F09 FE search-state sync, F11 pagination/trade-truncation disclosure, F12 full score-history pinning (design follow-up), Q01/Q06 test infrastructure, Q03 input validation, Q04 failure-persistence rollback, Q05 envelope boundary, U04 keyboard row actions, U07 loading states, U09 menu/toast disclosure, S04 refresh rotation + CSP. P2 — U10 theme metadata, password-reset flow.





### Remediation batch 5 — search correctness and response boundary

Re-read the findings and remediation history before continuing. These changes do not close the entire audit.

- **F09:** Search follows the current URL query, queries the full tracked company catalogue with server-side `q`, clears stale results, and ignores responses after the query changes or the page unmounts. Name searches no longer invoke ticker ingestion. Search copy describes companies/tickers only. Results remain capped at 100 matches; pagination remains **F11 open**.
- **Q05:** Replaced private Starlette `body_iterator` access with ASGI response messages. Invalid/empty JSON preserves its original bytes; non-JSON streams, encoded bodies, HEAD and bodyless statuses pass through. Wrapping preserves duplicate cookies and removes stale representation validators. JSON responses still require buffering and parsing; that overhead is not claimed eliminated.
- **U04/U05 (Search only):** Company tickers are keyboard-accessible links; the search field has an accessible name and length limit. Other pages remain open.
- **U08:** Removed the empty mobile top-header gap while retaining desktop spacing.
- **F14:** Late 401 responses from a previous session cannot refresh or clear a newer login. Removed the request to the nonexistent Rails logout endpoint. Logout remains local; **S04 server revocation/rotation stays open**.
- Corrected earlier migration guidance: deleted-revision reconciliation requires schema inspection, not blind stamping. Corrected the legacy-alert description to quarantine, rather than grandfathering.

**Verification:** Python suite **198 passed** (12 new ASGI boundary regressions); frontend ESLint and production build passed. No live database migrations or browser journeys were run for this batch. Durable queue reservation, crash recovery, scheduler ownership and migration upgrade paths still require integration verification; earlier green unit-suite claims do not establish these behaviors.

### Remediation batch 6 — backtest validation and failure persistence

- **Q03 (backtest requests):** Strategy-specific parameter validation rejects zero/negative/fractional/boolean rebalance intervals, invalid lookbacks/top-N, out-of-range thresholds and allocation weights, unknown options, and unsupported risk profiles before queue reservation. Empty parameter dictionaries preserve engine defaults. Names/tickers have database-compatible limits; capital must be finite and positive; empty ticker lists and nonpositive snapshot IDs are rejected. Mixed naive/aware dates produce validation errors rather than an unhandled comparison exception. Other domain schemas remain open under Q03.
- **Q04 (partial):** Backtest execution errors roll back partial work before reloading the durable queued row and saving failed status. Analysis failure-persistence errors are logged and propagated to the durable worker instead of silently swallowed; cancellation retains its rollback path. This does not claim that every exception path in every worker has been reconciled.

**Verification:** Python suite **225 passed**, including 26 new request-validation cases and one failure-ordering regression exercising rollback → reload → failure commit; `git diff --check` clean. The failure regression uses a simulated database failure; real PostgreSQL transaction recovery, migration upgrades and worker termination remain integration-test requirements. No frontend files changed in this batch.

### Remediation batch 7 — shared throttles, session revocation, and polling

- **S03 implementation:** Python paid-work budgets use an atomic Redis sliding-window script with Redis server time, expiring keys and opaque hashed identifiers. Redis outages return 503 with Retry-After rather than bypassing limits. Missing Redis configuration is allowed only in explicit development (or when throttling is explicitly disabled). Analysis, optimizer, backtest-run and snapshot creation are covered, including trailing-slash variants. Forwarded user identity is trusted only with the internal service credential; arbitrary forwarded IP/user headers cannot select another budget. Rails register/login/refresh now enforce shared PostgreSQL IP/account counters (60 IP requests/minute, 10 login/register attempts/account/minute), with bounded expired-counter cleanup and 429/503 responses.
- **S04 implementation (gateway):** New Rails AuthSession records bind access and refresh tokens to revocable sessions. Refresh rotates a random nonce under a row lock and rejects replay; authenticated gateway requests verify the session remains active. `/auth/logout` revokes that session, and the FE calls it while immediately clearing local state. Existing sessionless JWTs require sign-in again. Offline logout clears local credentials but cannot guarantee server revocation. CSP and browser storage hardening remain open. Direct Python bearer authentication has not been given a Rails-session lookup; this guarantee applies to the gateway, and Python must remain internal in production.
- **S01 remainder:** Rails production boot also rejects empty secrets and disabled authentication.
- **O09 partial:** Shared polling utility pauses Dashboard, analysis-list and analysis-detail polling in hidden tabs, resumes on visibility, serializes requests, stops terminal detail polling, and invalidates late responses after cleanup. Filter debounce and other page-specific stale-response checks remain open. Added a dependency-free frontend test command (`npm test`).
- **U01 correction:** Removed the still-present 45% Dashboard gauge fallback found during this pass. Prior claims that this particular expression was already gone were incorrect.

**Required rollout:** Apply Rails migrations `20260930000100_create_auth_throttles` and `20260930000200_create_auth_sessions` before serving the new gateway. This pass did not apply migrations. Users with existing JWTs must sign in again. Ensure Redis is configured for the Python service. Existing compose migration ordering remains in effect.

**Verification:** Python **229 passed**; standalone Ruby JWT service tests **4 passed / 9 assertions** (rotation, replay, revocation, simulated concurrent refresh); frontend polling tests **3 passed**; frontend lint/build passed; edited Ruby service/controller/migration syntax checks passed. Ruby locking tests use an in-memory session double, and Redis tests simulate responses/outages: neither proves live cross-process behavior. Docker daemon is unavailable (`docker.sock` absent), so PostgreSQL migrations, PostgreSQL throttle concurrency, real Redis Lua execution, two-browser auth journeys and worker termination tests remain open. The full audit is not closed.

### Remediation batch 8 — lean list queries and readable navigation feedback

- **O05:** Analysis-job, backtest-run and snapshot-list queries now select only response fields, excluding heavy analysis JSON, strategy parameters and snapshot datasets. Deferred fields use `raiseload` so accidental future reads fail visibly rather than introducing hidden queries. Added primary-key tie-breakers to list ordering. Ownership predicates are unchanged. Real query plans/load benchmarks remain outstanding.
- **U04/U05 (header):** Brand navigation is a real keyboard-accessible link; global search has an accessible name, matching delivered capabilities, and a length limit.
- **U09 (partial):** Account options expose expanded state and close on Escape (restoring trigger focus), outside pointer/focus movement and navigation. Long alert messages wrap instead of truncating. Toasts fit narrow viewports and wrap long/unbroken text. No browser accessibility claim is made from source checks alone.
- **F03/F14:** Unread-badge responses are invalidated on account changes/unmount, and older refresh responses cannot overwrite newer badge results.

**Verification:** Full Python suite **232 passed**, including three compiled-query regressions; after strengthening the snapshot-payload assertions those three tests passed again. Frontend **3 polling tests passed**, ESLint and production build passed; diff whitespace checks clean. Browser interactions, database query plans, live migration/session/rate-limit checks and scheduler/worker recovery remain open. This is another partial remediation batch, not full audit closure.
