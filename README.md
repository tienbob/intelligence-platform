# Intelligence Platform v2.0

**Domain-agnostic AI research engine.**

The core knows **HOW** to run intelligence.
The domain knows **WHAT** intelligence means.

## Architecture

```
intelligence-platform/
├── app/
│   ├── core/                    # General infrastructure (database, logging, security, caching)
│   ├── intelligence/            # Core engine (pipeline, registry, contracts)
│   ├── shared/                  # Domain-neutral entities and types
│   ├── domains/                 # Pluggable domain packs
│   │   ├── stock/               # Stock & Investment Intelligence
│   │   └── hr/                  # HR Intelligence (placeholder)
│   ├── workers/                 # Domain-agnostic scheduler
│   └── main.py                  # Auto-discovers and mounts domains
```

## Pipeline

```
Request → Domain Resolver → Ingestion → Normalization →
Entity Resolution → Evidence Collection → RAG Retrieval →
Context Builder → LLM → Structured Validation →
Domain Scoring → Result
```

## Adding a New Domain

1. Create `app/domains/<name>/` with a `manifest.py`
2. Implement the `DomainModule` protocol (see `app/intelligence/contracts.py`)
3. Set `INTELLIGENCE_DOMAINS=stock,<name>` (or omit to enable all)
4. Restart — the registry auto-discovers it

**No changes to core needed.**

## Domain Contract

Each domain must provide:
- `get_providers()` — data sources
- `get_normalizers()` — data transformation
- `get_context_builder()` — LLM context construction
- `get_scoring_strategy()` — domain-specific scoring
- `get_intelligence_tasks()` — background jobs
- `get_api_router()` — FastAPI endpoints
- `get_prompts()` — LLM prompt templates
- `get_schemas()` — Pydantic schemas
- `get_models()` — SQLAlchemy models
- `get_config()` — domain configuration

## Current Domains

| Domain | Status | Description |
|--------|--------|-------------|
| `stock` | Placeholder | Stock & investment intelligence (migrate from market-intelligence/) |
| `hr` | Placeholder | HR intelligence: candidate scoring, job matching, salary benchmarking |

## Migration from market-intelligence/

The `stock/` domain is a placeholder with the complete structure ready.
To activate it:

1. Copy provider implementations from `market-intelligence/app/providers/` into `domains/stock/providers.py`
2. Copy model definitions from `market-intelligence/app/models/` into `domains/stock/models/`
3. Copy context builder logic from `market-intelligence/app/services/context_builder.py` into `domains/stock/context_builder.py`
4. Copy scoring engine from `market-intelligence/app/services/investment_scoring.py` into `domains/stock/scoring.py`
5. Copy API endpoints from `market-intelligence/app/api/v1/` into `domains/stock/api.py`
6. Copy worker implementations from `market-intelligence/app/workers/` into `domains/stock/workers.py`

## Environment Variables

```bash
# Enable specific domains (comma-separated)
INTELLIGENCE_DOMAINS=stock,hr

# Core settings (see app/core/config.py)
DATABASE_URL=postgresql+asyncpg://...
LLM_API_KEY=...
REDIS_URL=...
```

## Running

```bash
uvicorn app.main:app --reload
```

## Key Design Principles

1. **Core never imports domain code** — domains are discovered via the registry
2. **Domain owns its data model** — each domain has its own tables
3. **Scoring is domain-specific** — the interface is general, the algorithm is not
4. **LLM/RAG/Embeddings are general** — they work the same for any domain
5. **Providers are abstracted** — swap data sources without changing core