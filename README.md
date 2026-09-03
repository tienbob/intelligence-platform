# Intelligence Platform (Architecture V3)

**Domain-agnostic AI research engine.**

The framework knows **HOW** to run intelligence.
The domain knows **WHAT** intelligence means.

> **Current status:** The V3 framework is the **production analysis engine**
> for both API and scheduled worker entry points (Gate 5.2 switchover complete).
> Legacy analysis orchestration removed (Gate 6 cleanup complete). Storage
> ownership matches the target architecture (Gate 4 complete). All gates
> 1–6 pass; Gate 7 (documentation audit) and Gate 8 (production integrity
> audit) in progress.

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
cp .env.example .env          # then fill in provider API keys
docker compose up --build     # db, redis, python :8001, rails :3000, frontend :3000
```

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
.venv/bin/python -m pytest -q
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

- `intelligence-platform-stock/docs/INTELLIGENCE_PLATFORM_ARCHITECTURE_V3.md` — authoritative architecture spec
- `intelligence-platform-stock/docs/CHECKLIST.md` — gated completion roadmap (Gate 0–6)
- `intelligence-platform-stock/docs/Audit_result.md` — Phase 12 audit results
