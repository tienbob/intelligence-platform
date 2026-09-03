# Table Ownership Registry

**Gate 4.1 artifact.**

**Classification basis (revised per audit):** *primary* basis is semantic
ownership and data contract — what does the table represent, who owns its
contract, who may write it, which ORM/migrations own it. Writer scans are used
to **verify enforcement** of that ownership, never as the definition.
Enforcement-evidence scans cover **both services sharing this database**
(Python `app/`, Rails `intelligence-platform-api/app/`) — a Python-only scan
misclassified the live Rails-owned `users` table as a retire candidate, which
is why this rule exists (2026-08 audit).

## Categories (five)

| Category | Meaning |
|---|---|
| **framework-owned** | Serves any domain generically (vector index, evidence). ORM lives in `app/intelligence/models/`; domains consume via framework contract/injection only. Writes outside framework code forbidden (§4.3 guard). |
| **domain-owned (stock)** | Models a stock-domain concept. ORM in `app/domains/stock/models/`; written exclusively through the stock persistence path. |
| **application-owned** | Application/platform concern that is neither intelligence-framework nor a domain concept: identity and access control (`users`, `user_companies`). Semantic owner is the application/auth layer (Rails gateway is the authoritative enforcer); DDL is provisioned via Alembic because `python-migrate` is the only migration pipeline deployed. Python must never write these tables and must not contain authorization logic — it only reads scope. |
| **infrastructure** | Owned by tooling (Alembic); never touched by application code. |
| **legacy — retire candidate** | No ORM class and no reference anywhere in either codebase. Drop decision belongs to Gate 6 cleanup, NOT Phase 15. |

## Explicitly shared?

Not required. The only candidate was `analyses` (API + worker + Gate 3 all
create rows), but every writer routes through one canonical writer
(`services/company_analysis.py`) enforcing one contract — so ownership stays
unambiguous: **stock-domain-owned**.

## Access-scoping contract (users ↔ companies)

```text
users ──< user_companies >── companies
```

`user_companies` is the junction granting a user visibility of specific
tracked companies. Contract:

* Company listing/detail endpoints show **only** companies linked to the
  requesting user — never the whole DB (product requirement, 2026-08).
* Every other company-data endpoint follows the same rule: news, events,
  prices, financials, stocks, analysis, alerts, market, portfolio, and
  investment-opportunities all filter to the requesting user's granted
  companies when `X-User-Id` is present.
* Backtesting is scoped by **owner** (not by company — backtests aren't
  company-keyed; company data is embedded in JSON snapshots):
  * `backtest_runs.user_id` — a run is a *private* user action; a scoped user
    sees only their own runs (`list`/`get`/`trades`, migration `0019`).
  * `backtest_snapshots.user_id` — snapshots are shared reference datasets
    (`NULL` owner = global, e.g. the scheduler's daily snapshot). A scoped
    user sees their own **plus** global ones, never another user's private
    snapshots.
* Rails gateway authenticates and forwards `X-User-Id` on every proxied call
  (`PythonClient` already sends it); Python resolves scope from that header.
* Enforcement of *assignment* is Rails/application-side. Python performs
  read-scoping only; it contains no authorization rules.

## Registry

### Framework-owned (1)

| Table | Evidence |
|---|---|
| `embeddings` | Generic pgvector index across entity types (`analysis,event,news`). **ORM is framework-owned (Gate 4.2):** `app/intelligence/models/embeddings.py` (re-exported via `app.intelligence.embeddings`); identity is fully generic `(domain, entity_type, entity_id)` — `domain` column via Alembic `0020`. Write mechanics live domain-free in `app/intelligence/embeddings/` (`PgVectorStore` resolves to the framework model). Stock consumes through the framework contract/injection (`app/domains/stock/scoring/embeddings.py` tags `domain="stock"`); it no longer defines any embedding model. |

### Domain-owned: stock (27)

All have exactly one writer package (`app/domains/stock`) in the scan; tests
exercise them through the same public paths.

> Macro note: `economic_indicators` / `raw_macro_data` remain stock-owned in
> Phase 15; generalizing macro into shared infrastructure is deferred. Decision
> test if revisited: is the table a Stock concept, or a generic observation
> source merely consumed by Stock?

| Table | Class |
|---|---|
| `alerts` | `Alert` |
| `analyses` | `Analysis` — canonical writer `services/company_analysis.py`; API, worker and Gate 3 persist through it |
| `analysis_sources` | `AnalysisSource` |
| `anomaly_scores` | `AnomalyScore` |
| `backtest_ai_evaluations` | `BacktestAIEvaluation` |
| `backtest_benchmarks` | `BacktestBenchmark` |
| `backtest_results` | `BacktestResult` |
| `backtest_runs` | `BacktestRun` |
| `backtest_score_evaluations` | `BacktestScoreEvaluation` |
| `backtest_snapshots` | `BacktestSnapshot` |
| `backtest_trades` | `BacktestTrade` |
| `companies` | `Company` |
| `company_news` | `CompanyNews` |
| `economic_indicators` | `EconomicIndicator` |
| `event_price_correlations` | `EventPriceCorrelation` |
| `financial_metrics` | `FinancialMetric` |
| `financial_statements` | `FinancialStatement` |
| `investment_scores` | `InvestmentScore` |
| `market_events` | `MarketEvent` |
| `news` | `News` |
| `raw_macro_data` | `RawMacroData` |
| `raw_market_data` | `RawMarketData` |
| `raw_news` | `RawNews` |
| `raw_sec_filings` | `RawSecFiling` |
| `risk_metrics` | `RiskMetric` |
| `stock_prices` | `StockPrice` |
| `technical_indicators` | `TechnicalIndicator` |

### Application-owned (2)

| Table | Status / Evidence |
|---|---|
| `users` | **Retained** pending the User ↔ Company access migration — do **not** drop in Phase 15. Live production identity store written by the Rails gateway: `auth_controller.rb` (`User.new`, `User.find_by(email:)`), `authenticatable.rb` (`@current_user = User.find_by(id: payload["sub"])`), `db/schema.rb` full auth schema (`encrypted_password`, `role`, `is_active`, reset tokens). *(Corrected 2026-08: previously misfiled as a Rails leftover by a Python-only scan.)* |
| `user_companies` | Junction table (target state, added with Gate 4): `id`, `user_id FK→users.id`, `company_id FK→companies.id`, timestamps, `UNIQUE(user_id, company_id)`. Implements the access-scoping contract above. Semantic owner: application/auth layer; DDL via Alembic `0016_user_companies`; assignment enforced in Rails, Python read-scopes via `X-User-Id`. |

### Infrastructure (3)

| Table | Owner |
|---|---|
| `alembic_version` | Alembic migration tooling |
| `schema_migrations` | Rails migration bookkeeping (persists) |
| `ar_internal_metadata` | Rails metadata (persists) |

### Legacy — retire candidates (6)

No ORM class and zero references across **both** codebases; row counts from
`pg_stat_user_tables`.

| Table | Rows | Origin hypothesis |
|---|---|---|
| `portfolio_allocation_history` | 0 | Abandoned portfolio feature (Python references the *concept* in schemas/optimizer output, but no code touches these tables) |
| `portfolio_drift_alerts` | 0 | ″ |
| `portfolio_holdings` | 0 | ″ |
| `portfolio_rebalance_trades` | 0 | ″ |
| `portfolio_recommendations` | 0 | ″ |
| `portfolios` | 0 | ″ |

(`users` was moved OUT of this list into application-owned — see above.)

## Footer — reconciliation

Live today (**38 tables**, pre-`user_companies`):
1 framework + 27 stock-domain + 1 application (`users`)
+ **3** infrastructure + **6** legacy-retire = **38** ✓

Target state after Gate 4 additions (**39 tables**):
adds `user_companies` → 1 + 27 + **2** application + **3** + **6** = **39** ✓

Every table accounted for; classification is semantic-first with writer-scan
enforcement evidence from both codebases.

## §4.3 CI guard lists derived from this registry

Explicit allow-lists only — there is deliberately **no** "everything else"
rule; an unclassified table must fail the guard:

```python
FRAMEWORK_OWNED_TABLES   = {"embeddings"}
STOCK_OWNED_TABLES       = { ...the 27 names above... }
APPLICATION_OWNED_TABLES = {"users", "user_companies"}
INFRASTRUCTURE_TABLES    = {"alembic_version"}
RETIREE_CANDIDATES       = { ...the 8 names above... }

# Guard rule: introspect scratch-DB tables after migrations;
# assert table_set ⊆ (union of the five sets). Any table outside
# the union, or present in two sets, → FAIL.
```