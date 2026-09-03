# Migration Audit Report — Rails & Python (Alembic)

**Scope:** All database migration files in the `intelligence-platform` monorepo.
**Date of audit:** 2026-08-27
**Repository:** `/Users/bob/Work/Market Research/intelligence-platform`

---

## 1. Environment & Tooling Summary

The platform is a **polyglot, shared-database system**: one PostgreSQL + pgvector DB is shared across a Python (FastAPI/Alembic) service and a Ruby (Rails/ActiveRecord) API gateway, with a React frontend.

| Service | Stack | Migration framework | Migration dir | # files |
|---|---|---|---|---|
| `intelligence-platform-stock` | Python / FastAPI | **Alembic 1.14** (async, `asyncpg`) | `migrations/versions/` | 16 |
| `intelligence-platform-api` | Ruby / Rails 8.0 | **ActiveRecord** | `db/migrate/` | 3 |
| `intelligence-platform-frontend` | React | — | — | — |

**Orchestration (`docker-compose.yml`):**
- `rails-migrate` (`bundle exec rails db:prepare`) runs **first**.
- `python-migrate` (`alembic upgrade head`) runs **after** `rails-migrate`.
- Then `rails` (puma) and `python` (uvicorn) start.

Single shared DB ⇒ table ownership split across two pipelines; `db/schema.rb` is a Rails dump of the *entire* shared DB (includes Alembic tables + `alembic_version`) → schema-load vs migration-run semantics are ambiguous (see §5.2).

---

## 2. Migration Inventory

### 2.1 Rails migrations (`intelligence-platform-api/db/migrate/`)

| # | Timestamp | File | Purpose |
|---|---|---|---|
| R1 | `20260810022034` | `create_users.rb` | Creates `users` (bigint id, email/name/role/is_active, `password_hash`, timestamps; unique email). Mirrors Python `users` schema. |
| R2 | `20260810024236` | `add_user_id_to_portfolios.rb` | `add_reference :portfolios, :user, null: false, foreign_key: true`. |
| R3 | `20260810025318` | `add_devise_to_users.rb` | Devise: renames `password_hash → encrypted_password`; adds recoverable/rememberable cols + unique `reset_password_token` index. `up`/`down`. |

### 2.2 Python (Alembic) migrations (`intelligence-platform-stock/migrations/versions/`)

| # | Rev | File | Purpose |
|---|---|---|---|
| P1 | `0001` | `0001_initial.py` | pgvector extension + 24 base tables (`companies`…`alerts`). Full downgrade. |
| P2 | `0002` | `0002_embedding_vector.py` | `embeddings.embedding`: `ARRAY(Float)` → `vector(1536)` (fixes pgvector `<=>`). |
| P3 | `0003` | `0003_stockprice_unique.py` | `interval` default `'1d'` + unique `(company_id,interval,timestamp)`. |
| P4 | `0004` | `0004_unique_financial_macro.py` | Unique: `financial_statements(company_id,period)`, `economic_indicators(indicator,timestamp)`. |
| P5 | `0005` | `0005_unique_company_news.py` | Unique `company_news(company_id,news_id)`. |
| P6 | `0006` | `0006_event_materiality.py` | `materiality`/`effective_weight` on `market_events`+`news`; `extraction_method`/`confidence` on `company_news`; uid `(company_id,source_news_id,event_type)`. |
| P7 | `0007` | `0007_scoring_versioning.py` | Scoring-version cols on `investment_scores` + backfill UPDATE. |
| P8 | `0008` | `0008_portfolio_intelligence.py` | 3 tables: allocation_history / rebalance_trades / drift_alerts. |
| P9 | `0009` | `0009_embedding_dimensions.py` | Resize `vector(1536)` → `vector(3072)` (gemini-embedding-001). |
| P10 | `0010` | `0010_backtesting.py` | 7 backtest tables. |
| P11 | `0011` | `0011_add_provider_record_id.py` | Documented drift fix: `provider_record_id` on `stock_prices`. |
| P12 | `0012` | `0012_add_cash_balance.py` | `cash_balance` on `portfolios`; backfill from `capital`. |
| P13 | `0013` | `0013_add_version_column_to_portfolios.py` | `version` on `portfolios`. |
| P14 | `0014` | `0014_create_embeddings_table.py` | Recreate `embeddings` w/ `vector(3072)` via raw `IF NOT EXISTS` (schema.rb workaround). |
| P15 | `0015` | `0015_event_dedup_company_news.py` | De-dup `market_events` then uid swap `(company_id,source_news_id,event_type)`→`(company_id,source_news_id)`. |
| P16 | `0016` | `0016_user_companies.py` | `user_companies` junction + runtime guard + O(n×m) backfill. |

**Alembic chain:** `0001→…→0016`, strictly linear, no branches, `down_revision` correct throughout. ✔️
**Rails chain:** `022034→024236→025318`, linear. ✔️

---

## 3. Detailed File-by-File Audit

### 3.1 Rails migrations

#### R1 — `20260810022034_create_users.rb` — ✅ GOOD
`create_table :users, id: :bigint` with `email` (unique index), `password_hash`, `name`, `role` (default `"USER"`), `is_active` (default true), `t.timestamps`. Mirrors the Python `users` schema. `users.id` is `bigint`; Alembic P16 references `users(id)` as `BIGINT` — type-consistent. ✔️ `password_hash` renamed away in R3; fine on an empty table. ✔️

#### R2 — `20260810024236_add_user_id_to_portfolios.rb` — ⚠️ CRITICAL (§5.1)
`add_reference :portfolios, :user, null: false, foreign_key: true`. The `portfolios` table is **created by Alembic P1**, not Rails. Reversible `change`. On a fresh DB with Rails-first ordering, `portfolios` does not yet exist → `db:prepare` fails (`PG::UndefinedTable`). No guard.

#### R3 — `20260810025318_add_devise_to_users.rb` — ✅ GOOD
Explicit `up`/`down`. Renames `password_hash → encrypted_password`; adds recoverable/rememberable cols + unique `reset_password_token` index. Reversible & maps to the `User` model (`devise :database_authenticatable`). ✔️

### 3.2 Python (Alembic) migrations

#### P1 — `0001_initial.py` — ✅ Strong, minor issues
`revision="0001"`, `down_revision=None`. ✔️ pgvector extension; 24 tables + 26 indexes; full `downgrade()`. ✔️
- `embeddings.embedding` created as `ARRAY(Float)` — wrong type; corrected by P2.
- `embeddings.embedding_model` `nullable=False`, **no default** (ORM supplies one); default never applied on the migration chain (P14 is a no-op) — see §5.9.
- `server_default=sa.text("now()")` on every timestamp. ✔️

#### P2 — `0002_embedding_vector.py` — ✅ GOOD
Casts `ARRAY(Float)` → `vector(1536)` (`USING embedding::vector(1536)`); extension ensured (no-op). Symmetric downgrade. ✔️

#### P3 — `0003_stockprice_unique.py` — ✅ GOOD
`interval` default `'1d'` + unique constraint on `(company_id,interval,timestamp)`. Symmetric downgrade. ✔️ (ORM also defines a unique idx on same cols → redundant, §5.5.)

#### P4 — `0004_unique_financial_macro.py` — ✅ GOOD
Unique constraints + symmetric downgrade. ✔️ **Alignment verified:** ORM `FinancialStatement` uid `ix_financial_statements_company_period`; ORM `EconomicIndicator` uid `ix_economic_indicators_indicator_ts`. ✔️ (Name styling differs `uq_*` vs `ix_*` — cosmetic.)

#### P5 — `0005_unique_company_news.py` — ✅ GOOD (redundancy §5.5)
uid `uq_company_news_company_news(company_id,news_id)`; symmetric. ✔️ ORM `CompanyNews` declares a *unique index* of the same name → redundant constraint+index on identical columns.

#### P6 — `0006_event_materiality.py` — ✅ GOOD
Materiality/weight cols on `market_events`+`news`; extraction metadata on `company_news`; uid on `market_events`. Symmetric. ✔️ **Alignment verified:** `MarketEvent.materiality_score/effective_weight`, `News.materiality_score/effective_weight`, `CompanyNews.extraction_method/confidence` — all present. ✔️

#### P7 — `0007_scoring_versioning.py` — ✅ GOOD (redundancy §5.10)
5 cols on `investment_scores` + backfill UPDATE; symmetric. ✔️ **Alignment verified:** ORM `InvestmentScore` declares `scoring_model` (default `investment_score_v1`), `scoring_version` (default `1.0`), `scoring_weights`, `data_quality_score`, `validation_issues`. ✔️ Backfill UPDATE redundant (server_defaults auto-fill existing rows) — harmless/defensive.

#### P8 — `0008_portfolio_intelligence.py` — ⚠️ MEDIUM (§5.6)
3 tables (`portfolio_allocation_history`, `portfolio_rebalance_trades`, `portfolio_drift_alerts`); symmetric downgrade. ✔️ **Conflict:** `TABLE_OWNERSHIP.md` classifies **all portfolio tables as legacy-retire, 0 rows, no ORM model**. P8 *creates more* deprecated tables.

#### P9 — `0009_embedding_dimensions.py` — ✅ GOOD
Resizes `vector(1536)` → `vector(3072)` (gemini-embedding-001); symmetric. ✔️ DB column is 3072 while code default is 1536 (see §5.3).

#### P10 — `0010_backtesting.py` — ✅ GOOD
7 backtest tables + composite indexes; symmetric downgrade (reverse order). ✔️ **Alignment verified:** ORM `backtest.py` declares all 7 tables and indexes `ix_backtest_trades_run_date`, `ix_backtest_score_eval_run_ticker`. ✔️

#### P11 — `0011_add_provider_record_id.py` — ✅ GOOD (template drift-fix)
Nullable `provider_record_id VARCHAR(255)`; clear docstring; symmetric. ✔️ **Alignment verified:** ORM `StockPrice.provider_record_id: Mapped[str|None]=mapped_column(String(255))` — exact match. ✔️

#### P12 — `0012_add_cash_balance.py` — ⚠️ MEDIUM (§5.6)
`cash_balance FLOAT NOT NULL DEFAULT 0` + backfill from `capital`; symmetric. ✔️ Mutates deprecated `portfolios`. Stylistic: `server_default="0"` string on Float — Postgres casts fine.

#### P13 — `0013_add_version_column_to_portfolios.py` — ⚠️ MEDIUM (§5.6)
`version INTEGER NOT NULL DEFAULT 1`; symmetric. ✔️ Mutates deprecated `portfolios`.

#### P14 — `0014_create_embeddings_table.py` — ⚠️ MEDIUM (§5.4)
`CREATE TABLE IF NOT EXISTS embeddings (... vector(3072) ...)`; idempotent. ✔️ **Redundancy:** no-op on every normal upgrade (table already exists from P1→P2→P9); only acts as a schema.rb-load workaround. **Two divergent definitions** of `embeddings` (P1 vs P14): P14 has `embedding_model NOT NULL DEFAULT` and plain `JSONB`, P1 has none/`JSONB(astext_type=sa.Text())`.

#### P15 — `0015_event_dedup_company_news.py` — ✅ GOOD
De-dups `market_events` (NULL-safe `IS NOT DISTINCT FROM`, keeps max-id) **before** swapping uid `(company_id,source_news_id,event_type)` → `(company_id,source_news_id)`; symmetric. ✔️ Best practice. ORM `MarketEvent` uid matches the **new** constraint. ✔️

#### P16 — `0016_user_companies.py` — ⚠️ MEDIUM (§5.8 / §5.1)
`user_companies` junction via raw `IF NOT EXISTS` DDL + uid + company idx. **Runtime guard** checks `users` & `companies` exist with an actionable error. ✔️ **CROSS JOIN backfill is O(n×m), blocking.** ⚠️ No ORM model by design (Python must not write it). ✔️ Symmetric downgrade. ✔️

### 3.3 Supporting files
- **`migrations/env.py`** — async Alembic env; imports `app.domains.stock.models` to register metadata; overrides URL from settings. ✔️ Offline path `literal_binds=True`. ✔️
- **`alembic.ini`** — `sqlalchemy.url` points at `localhost:5432`, overridden at runtime by env.py from `DATABASE_URL` (L4 — misleading if read alone).
- **`bin/migrate.sh`** — skips if `db:migrate:status` shows no `down`; else `db:prepare`. ✔️
- **`scripts/migrate.sh`** — `alembic upgrade head`. ✔️

---

## 4. Cross-Cutting Analysis

### 4.1 Upgrade/downgrade symmetry
- **Alembic:** 16/16 have a working `downgrade()`; every `upgrade` op has a matching `downgrade` op (drop/revert). ✔️
- **Rails:** R1 reversible `change`; R2 reversible `add_reference`; R3 explicit `up`/`down`. ✔️
- **Lineage:** strictly linear, no branches, no gaps. ✔️

### 4.2 Idempotency
- Standard Alembic `op.create_table`/`op.add_column` are **not idempotent** (no `IF NOT EXISTS`) — fine for a single forward `upgrade head`. ✔️
- **Inconsistency:** P14 & P16 use raw `IF NOT EXISTS` DDL; P1–P13 use standard ops. Intentional, documented. ✔️

### 4.3 Cross-service table ownership (per `docs/TABLE_OWNERSHIP.md`)
- **Application-owned:** `users`, `user_companies` → semantic owner = Rails/auth; DDL via Alembic; Python never writes.
- **Framework-owned:** `embeddings`.
- **Domain-owned (stock):** 27 tables incl. `portfolios`, `companies`, `stock_prices`, etc.
- **Infrastructure:** `alembic_version`.
- **Legacy-retire (8):** portfolio tables (0 rows, no models) + Rails bookkeeping (`schema_migrations`, `ar_internal_metadata`).

### 4.4 Migration ↔ ORM alignment (sampled)
| Table | Feature | Migration | ORM | Match? |
|---|---|---|---|---|
| `stock_prices` | `provider_record_id` | P11 ✅ | `StockPrice` ✅ | ✅ |
| `embeddings` | `vector(3072)` | P9 ✅ | `Embedding` via `settings.EMBEDDING_DIMENSIONS` | ⚠️ config default 1536 (§5.3) |
| `market_events` | materiality cols | P6 ✅ | `MarketEvent` ✅ | ✅ |
| `market_events` | uid (co,news) | P15 ✅ | `MarketEvent` ✅ | ✅ |
| `news` | materiality cols | P6 ✅ | `News` ✅ | ✅ |
| `company_news` | extraction cols | P6 ✅ | `CompanyNews` ✅ | ✅ |
| `investment_scores` | scoring versioning | P7 ✅ | `InvestmentScore` ✅ | ✅ |
| `analyses` | full schema | P1 ✅ | `Analysis` ✅ | ✅ |
| `financial_statements` | uid (co,period) | P4 ✅ | `FinancialStatement` ✅ | ✅ |
| `economic_indicators` | uid (indicator,ts) | P4 ✅ | `EconomicIndicator` ✅ | ✅ |
| `stock_prices` | idx (co,interval,ts) | **NOT in migrations** | `StockPrice` idx ✅ | ❌ (§5.7) |

### 4.5 `db/schema.rb` fidelity
`schema.rb` is a Rails dump of the **shared** DB and contains Alembic-created tables + `alembic_version`. It is **not** a faithful dump of "Rails migrations only" — see §5.2.

---

## 5. Issues, Risks & Recommendations

### 🔴 CRITICAL

#### 5.1 Circular cross-pipeline dependency (Rails R2 ↔ Alembic P1) — blocks fresh DBs
**Where:** `db/migrate/20260810024236_add_user_id_to_portfolios.rb`.
**Problem:** R2 adds `user_id` + FK to `portfolios`, but `portfolios` is created by **Alembic P1**. docker-compose runs `rails-migrate` **before** `python-migrate`. On a fresh DB, R2 fires while `portfolios` does not yet exist → `db:prepare` aborts → `PG::UndefinedTable` → cascades to blocking `python-migrate` + both apps. The mirror side (Alembic P16 needing `users`) **is** guarded, but R2 has **no guard**; failure is opaque.
**Recommendation (choose one):**
1. *(Preferred)* Move `user_id` FK into Alembic (a `0017_add_user_id_to_portfolios.py` referencing `users.id`, guarded like P16), and **delete R2** — `portfolios` is Alembic/domain-owned per `TABLE_OWNERSHIP.md`. This breaks the cycle cleanly.
2. Reorder `python-migrate` before `rails-migrate` — but then P16's guard fires (`users` missing). Would require splitting P16. Messy.
3. Make `schema.rb` the single fresh-DB source and make **every** Alembic migration idempotent. Largest change.
**Severity:** CRITICAL.

#### 5.2 `db:schema:load` vs `alembic upgrade head` are mutually incompatible on a fresh DB
**Where:** interaction of `db/schema.rb` with `alembic upgrade head`.
**Problem:** `db:prepare` on an empty DB **loads `schema.rb`**, which contains **all** Alembic tables + `alembic_version`. Then `alembic upgrade head` sees an **empty `alembic_version`** and runs P1 → `op.create_table("companies")` → **`relation already exists` → Alembic aborts**. Conversely (no schema load) R2 fails (§5.1).
**Recommendation:** Pick and document **one** fresh-DB path. Cleanest: Alembic creates stock schema; Rails creates only `users`; **do not** let `db:prepare` schema-load the Alembic tables (seed `schema_migrations` so Rails runs migrations, or exclude Alembic tables from `schema.rb`). Add an **end-to-end provisioning test** (fresh DB → both pipelines succeed).
**Severity:** CRITICAL.

### 🟠 HIGH

#### 5.3 Embedding dimension config drift (mitigated only by `.env`)
**Where:** P9 (`vector(3072)`) vs `app/core/config.py` default `EMBEDDING_DIMENSIONS = 1536`.
**Problem:** DB column is `vector(3072)` (P9) and the model `gemini-embedding-001` produces 3072 dims. But the code **default** is 1536. ORM `Embedding` uses `AsyncVector(settings.EMBEDDING_DIMENSIONS)`; persistence guard validates `len(vec) == settings.EMBEDDING_DIMENSIONS`. `.env.example` sets `EMBEDDING_DIMENSIONS=3072` (so docker/ compose deployments are fine), but **without `.env`**: `create_all` makes `vector(1536)` while writes produce 3072-dim vectors → dimension-mismatch errors on every embedding write.
**Recommendation:** Set code default `EMBEDDING_DIMENSIONS = 3072` in `config.py`; add a startup assertion that `settings.EMBEDDING_DIMENSIONS` matches the actual DB column width.
**Severity:** HIGH (live in local/test/dev without `.env`).

#### 5.4 `embeddings` table created by two migrations (P1 + P14) with divergent definitions
**Where:** P1 vs P14.
**Problem:** P14's `CREATE TABLE IF NOT EXISTS embeddings` is a **no-op** on every normal upgrade (table exists from P1→P2→P9); it only fires as a schema.rb-load workaround. Two divergent definitions exist (P1: `ARRAY`→cast, no default; P14: `vector(3072)`, `embedding_model NOT NULL DEFAULT`, plain `JSONB`). Confusing tech debt.
**Recommendation:** Remove P14 once §5.2 is resolved, or fold the `embedding_model` default into a dedicated tiny migration and document P14's single purpose.
**Severity:** MEDIUM-HIGH.

### 🟡 MEDIUM

#### 5.5 Redundant unique structures (constraint + index on same columns)
**Where:** `company_news` (P1 non-unique idx `ix_company_news_company_news`; P5 unique constraint `uq_*`; ORM unique idx of same name) and `market_events` (P15 uid + ORM uid). **Problem:** same columns carry both a unique constraint and a unique index (different names). Functionally fine, wasteful/confusing in introspection.
**Recommendation:** Consolidate to one mechanism; align names.
**Severity:** LOW-MEDIUM.

#### 5.6 `portfolios` is a deprecated table that still receives migrations
**Where:** P8, P12, P13, Rails R2 vs `TABLE_OWNERSHIP.md`.
**Problem:** `portfolios` + all `portfolio_*` tables are **"legacy — retire candidates"**, 0 rows, **no `Portfolio` model in Rails or Python**. Yet P8 creates three more, and P12/P13 add columns to `portfolios` — building schema for a feature with no owner.
**Recommendation:** Either (a) confirm deprecation and **drop** P8/P12/P13/R2 (clean up `schema.rb` too), or (b) revive + add the missing `Portfolio` model(s) and reclassify.
**Severity:** MEDIUM.

#### 5.7 `stock_prices.company_interval_ts` index missing from migrations
**Where:** P1 (0001) vs ORM `StockPrice` vs `schema.rb` (line 571).
**Problem:** ORM declares `Index("ix_stock_prices_company_interval_ts","company_id","interval","timestamp")` and `schema.rb` has it — **but no Alembic migration creates it** (P3 only adds the uid). Production deploy = `upgrade head` (not `create_all`), so **this compound index is absent** after a migration-only deploy, weakening range queries.
**Recommendation:** Add the index to a migration.
**Severity:** MEDIUM.

#### 5.8 `P16` user×company backfill is O(n×m) and blocking
**Where:** `0016_user_companies.py`.
**Problem:** `INSERT … SELECT u.id, c.id FROM users u CROSS JOIN companies c ON CONFLICT DO NOTHING` — full cross product in one statement; heavy locks.
**Recommendation:** For non-dev envs, batch the insert (per-user chunks) or defer to a queued job. Document the small-table assumption.
**Severity:** MEDIUM.

#### 5.9 `embeddings.embedding_model` has no default on the migration chain
**Where:** P1 (`nullable=False`, no default); P14 would add one but is a no-op.
**Problem:** Direct SQL / new code paths omitting `embedding_model` fail. Persistence layer always supplies it, so latent not live.
**Recommendation:** Add a tiny migration setting `server_default='text-embedding-3-small'`.
**Severity:** LOW-MEDIUM.

#### 5.10 Redundant backfill in P7
**Where:** `0007_scoring_versioning.py`.
**Problem:** `UPDATE … WHERE scoring_model IS NULL` is redundant (`scoring_model`/`scoring_version` carry server_defaults → auto-filled).
**Recommendation:** Remove, or keep as explicit guarantee with a comment.
**Severity:** LOW.

### 🔵 LOW / Conventions
| ID | Finding | File | Severity |
|---|---|---|---|
| L1 | Inconsistent `Revises:` comment style (P12 writes `0011_add_provider_record_id`; others bare `0011`). Chain intact. | `0012_add_cash_balance.py` | Trivial |
| L2 | Index name styling mismatch `uq_*` (migrations) vs `ix_*` (ORM). Not functional. | various | Trivial |
| L3 | Docstring depth uneven (P2/P9/P11/P14/P15/P16 verbose; P3/P4/P5/P7/P12/P13 terse). | various | Consistency |
| L4 | `alembic.ini` `sqlalchemy.url` = `localhost:5432`, overridden at runtime. Misleading if read alone. | `alembic.ini` | Trivial |
| L5 | P15 de-dup DELETE is lossy-by-design (documented). | `0015_…` | Acceptable |

---

## 6. Strengths (what the team did right)
1. **Reversible:** 16/16 Alembic + 3/3 Rails have working `downgrade`. ✔️
2. **Linear chains**, no branches/orphans. ✔️
3. **Reactive migrations are well-documented** (P2/P9/P11/P14/P15/P16 explain *why*). ✔️
4. **P16 runtime guard** with an actionable error naming `rails-migrate`/`python-migrate`. ✔️
5. **P15 de-dup-before-constraint** best practice. ✔️
6. **Cross-service FK `portfolios.user_id → users.id`** declared & enforced. ✔️
7. **Strong migration↔ORM alignment** for Phase-4/6/7 features. ✔️
8. **Idempotency where it matters** (P14/P16) with rationale. ✔️

---

## 7. Table & Column Inventory (at head)

**Alembic end-state** (35 user tables + infra `alembic_version`) + Rails `users` + bookkeeping (`schema_migrations`, `ar_internal_metadata`).

Key cross-service / deprecated tables:
- `portfolios` — created P1; mutated P12, P13; FK `user_id`→`users` via Rails R2. **Deprecated** (0 rows, no model).
- `embeddings` — P1 (ARRAY) → P2 (vector 1536) → P9 (vector 3072); P14 recreates idempotently. Framework-owned.
- `market_events` — unique (company_id, source_news_id) post-P15; ORM matches.
- `user_companies` — P16; uid (user_id, company_id); cross-FK → `users`(Rails) + `companies`(Alembic); backfilled.

**Total:** 35 (Alembic) + 1 (`users`) + 1 infra + 2 bookkeeping = 39, matching `TABLE_OWNERSHIP.md` target. ✔️

---

## 8. Action Priority

| Priority | Issue | Quick fix |
|---|---|---|
| P0 | 5.1 Circular cross-pipeline FK (R2 needs Alembic's `portfolios`) | Move `user_id` FK into Alembic (`0017`); delete R2 |
| P0 | 5.2 `schema.rb` load vs Alembic mutually exclusive on fresh DB | Pick one fresh-DB path; add provisioning test |
| P1 | 5.3 Embedding dim code default 1536 vs DB 3072 | `config.py` default → 3072; startup assertion |
| P1 | 5.4 Dual `embeddings` definition | Resolve P14 once 5.2 settled |
| P2 | 5.6 Portfolios deprecated but still migrated | Drop P8/P12/P13/R2 or revive + add models |
| P2 | 5.7 Missing `company_interval_ts` index | Add to a migration |
| P3 | 5.8 P16 O(n×m) backfill | Batch for prod |
| P3 | 5.5 Redundant unique constraint+index | Consolidate |
| P4 | 5.9 `embedding_model` no default | Add default migration |
| P4 | L1–L5 | Conventions/cleanup | Style tweaks |

---

*End of report.*


