# Intelligence Platform (Architecture V3)

**Domain-agnostic AI research engine.**

The framework knows **HOW** to run intelligence.
The domain knows **WHAT** intelligence means.

> **Current status:** the Stock framework analysis path is implemented,
> including persisted-data ingestion, context assembly, company-scoped RAG,
> scoring, evidence and result persistence. Select it with
> `ANALYSIS_ENGINE=framework`; framework is the only supported engine.
> Completing this path does not imply that production rollout gates are
> complete. See the [framework path guide](intelligence-platform-stock/docs/FRAMEWORK_ANALYSIS_PATH.md)
> and [implementation plan](intelligence-platform-stock/docs/PLAN.md).

## Repository Layout

```
intelligence-platform/
├── intelligence-platform-stock/       # Python app: framework + Stock domain pack
│   ├── app/
│   │   ├── core/                      # Infra (config, db, logging, versioning)
│   │   ├── intelligence/              # V3 FRAMEWORK — pipeline, registry, contracts,
│   │   │                              #   embeddings, RAG, LLM, evidence, validation
│   │   ├── shared/                    # Domain-neutral entities (EntityRef, Evidence…)
│   │   ├── domains/                   # Pluggable domain packs
│   │   │   ├── stock/                 #   Stock & investment intelligence (complete)
│   │   │   ├── example/               #   Minimal reference domain
│   │   │   └── hr/                    #   HR intelligence (deferred)
│   │   └── main.py                    # Auto-discovers and mounts enabled domains
│   └── docs/                          # Architecture V3, audits, checklist
├── intelligence-platform-api/         # Rails API gateway
├── intelligence-platform-frontend/    # React frontend
└── docker-compose.yml                 # db (pgvector) + redis + python + rails + web
```

## The Pipeline

The generic `IntelligencePipeline` (framework path) runs 12 stages:

```
Request → Domain Resolver → Ingestion → Normalization →
Entity Resolution → Evidence Collection → RAG Retrieval →
Context Builder → LLM → Structured Validation → Domain Scoring → Result
```

Every stage records an explicit status — `success`, `degraded`, `skipped`,
or `failed: <error>` — so partial data availability is observable instead of
silently swallowed.

## Running

```bash
cp .env.example .env          # first setup only; then fill in keys and settings
docker compose up -d --build
```

Open the frontend at **http://localhost:3000**. Rails and Python are internal
services behind the frontend proxy; Python listens on container port 8001.
Compose starts PostgreSQL with pgvector, Redis, migration services, the APIs,
the analysis worker and the ingestion scheduler. Migrations run before their
dependent services start.

Configure `LLM_PROVIDER`, `LLM_API_KEY` and `LLM_MODEL` for analysis, plus
`EMBEDDING_PROVIDER`, `EMBEDDING_API_KEY` and the embedding model settings for RAG.
The root `.env.example` lists the supported configuration fields.

Compose defaults to `ENVIRONMENT=development` for Python and Rails, including
Rails migrations. For production, set `ENVIRONMENT=production`, real
`SECRET_KEY_BASE`, `JWT_SECRET_KEY`, and `PYTHON_SERVICE_KEY` values, and
`AUTH_ENABLED=true` in the root `.env`. The gateway validates these settings
when migrations boot Rails as well as when the API starts.
Local Compose builds include Rails development gems. For production builds,
also set `RAILS_BUNDLE_WITHOUT=development:test` to exclude development and test
gems. Rebuild the Rails images after changing this setting.

## Market Data Providers

Active Stock ingestion uses:

| Provider | Data | Root `.env` settings |
|----------|------|----------------------|
| Twelve Data | Daily OHLCV history | `TWELVE_DATA_API_KEY` |
| Finnhub | Quotes, company profiles and news | `FINNHUB_API_KEY` |
| SEC | US USD financial statements | `SEC_USER_AGENT` with your organization and actual contact email |
| FMP | Optional fallback and market movers | `FMP_API_KEY`, subject to account entitlement |

Massive is no longer used by active provider routing. Its adapter and historical
source labels remain for compatibility. Existing articles labelled Massive can
still appear in retrieved evidence.

Twelve Data defaults to 8 credits per minute and 800 per day. Redis shares quota
reservations across workers; exhausted budgets defer remaining history work.
Provider coverage depends on the account tier. Missing financial inputs are
reported rather than treated as complete data. See the
[provider migration guide](intelligence-platform-stock/docs/PROVIDER_MIGRATION.md)
for coverage limits and migration 0021 requirements on existing databases.

## AI Analysis

Set the engine in the root `.env`:

```dotenv
ANALYSIS_ENGINE=framework
```

The framework reads stored company snapshots during a deep dive. Vendor fetching
is handled separately by ingestion workers. The framework uses deterministic
Python scoring; the LLM supplies the explanation. Legacy orchestration has been removed. Existing deployments must change
`ANALYSIS_ENGINE=legacy` to `ANALYSIS_ENGINE=framework` before restarting.
Optional news, fundamentals, technical and macro sections remain supported.

The **Opportunities** page uses each company's latest completed deep dive visible
to the signed-in user, with screening scores for companies awaiting analysis.
Its score and deep-dive link refer to the same analysis. Investment score and
risk score are separate measures.

Score components are bounded to 0–100. Financial-data coverage checks usable
fields and reporting freshness, and identifies components using the neutral
50 fallback. Score confidence is capped at 95%, or 50% when a financial component
uses fallback inputs; it describes evidence coverage, not the probability of
investment success. AI self-assessment remains separate.

Recent news and retrieved passages have citation IDs. Unsupported causes are
excluded and shown as evidence limitations. Citation checks establish plausible
textual support, not independent factual verification. Run a new deep dive to
apply changed analysis logic to a company; historical results retain their
original snapshots.

### Applying configuration and code changes

Changing runtime values in root `.env` does **not** require rebuilding images. Recreate the
services that consume the changed settings; a container restart alone does not
reload `env_file` values:

```bash
docker compose up -d --no-deps --force-recreate python worker scheduler
```

Rebuild for Python or frontend code changes. The Python API uses a development
bind mount, but worker and scheduler code is baked into their images:

```bash
docker compose up -d --build python worker scheduler frontend
```

If gateway settings change, recreate `rails` as well. Changes to dependencies or
build arguments, including frontend `VITE_REFRESH_*` settings, require rebuilding
the affected images. Let active analyses
finish before recreating their worker.

## Domain Enablement

Enabled domains come from an explicit allow-list — discovery on disk does
**not** imply activation:

```bash
INTELLIGENCE_DOMAINS=stock        # hr stays disabled even though it exists
```

Adding a domain later: create `app/domains/<name>/manifest.py` implementing
the `DomainModule` protocol (`app/intelligence/contracts.py`), add it to
`INTELLIGENCE_DOMAINS`, restart. No core changes needed.

## Tests

```bash
cd intelligence-platform-stock
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DEBUG=false REDIS_CACHE_ENABLED=false ANALYSIS_ENGINE=framework .venv/bin/python -m pytest tests -q
```

Keep the Compose Redis service running for the rate-limit integration test.
Tests use mocked providers and recorded LLM output; they do not establish live
provider entitlement or factual accuracy of model-generated prose.

Frontend checks:

```bash
cd intelligence-platform-frontend
npm ci
npm test
npm run build
```

Read-only comparison of framework contexts and persisted snapshot readers against the local database:

```bash
docker compose exec -T python python scripts/verify_framework_context.py
```

## Version Labels

Version identity is deliberately disambiguated (no single conflated
`version` field):

| Label                  | Owner                                   | Surfaced by |
|------------------------|-----------------------------------------|-------------|
| `application_version`  | `settings.APP_VERSION` (env-tunable)    | FastAPI + `GET /` |
| `architecture_version` | `app/core/versioning.py`                | `GET /` |
| `pipeline_version`     | `app/core/versioning.py`                | `GET /`, analysis metadata |
| `domain_version`       | each domain's manifest (`version`)      | `GET /domains`, analysis metadata |
| `scoring_version`      | Stock config `SCORING_VERSION`          | scoring provenance |
| `prompt_version`       | Stock manifest `PROMPT_VERSION`         | prompt provenance |

## Key Design Principles

1. **Framework never imports domain code** — enforced by purity tests
2. **Framework owns HOW, domain owns WHAT**
3. **Scoring is domain-specific** — the interface is general, the algorithm is not
4. **LLM/RAG/embeddings are general** — identical mechanics for any domain
5. **Failures are classified, never swallowed** — degraded ≠ success

## Documentation

- [Architecture V3](intelligence-platform-stock/docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md) — architecture specification
- [Framework analysis path](intelligence-platform-stock/docs/FRAMEWORK_ANALYSIS_PATH.md) — engine selection, persistence and quality safeguards
- [Provider migration](intelligence-platform-stock/docs/PROVIDER_MIGRATION.md) — provider setup, quotas and coverage limits
- [Implementation plan](intelligence-platform-stock/docs/PLAN.md) — rollout and completion gates
