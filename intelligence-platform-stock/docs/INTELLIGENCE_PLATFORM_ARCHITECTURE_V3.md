# Intelligence Platform Architecture v3

**Status:** Current architectural source of truth  
**Date:** 2026-08-25  
**Project:** Intelligence Platform  
**Primary reference domain:** Stock / Investment Intelligence  
**Current framework test status:** 103/103 passing  
**Current migration status:** Phase 12 complete; Phase 13 Shadow Production is next

---

## 1. Executive Summary

The Intelligence Platform is a **domain-agnostic intelligence framework** designed to make it possible to build multiple AI-powered intelligence products without reimplementing the same infrastructure for every domain.

The central architectural rule is:

> **The framework owns HOW intelligence works. The domain owns WHAT intelligence means.**

The platform is intentionally being built around a working Stock / Investment Intelligence implementation. Stock is the **reference implementation** and the primary stress test for the framework. The goal is not to rewrite Stock into a generic application, but to extract reusable mechanisms while preserving Stock-specific intelligence semantics.

The intended end state is:

```text
                         Intelligence Platform
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
    Intelligence Core       Shared Persistence       Registry / Scheduler
          │
    ┌─────┼─────────┬─────────┬─────────┬──────────┐
    │     │         │         │         │          │
    ▼     ▼         ▼         ▼         ▼          ▼
 Entity Providers  Obs.   Evidence  Embeddings   RAG     LLM / Validation
 Resolve                                              
          │
          ▼
   IntelligencePipeline
          │
    ┌─────┴─────────┐
    ▼               ▼
  Stock             Future Domains
  Domain            (HR, Legal, etc.)
```

The current state is no longer merely an architectural prototype. The platform has a working generic core and a fully wired Stock composition root. The remaining work is primarily **production equivalence, shadow execution, storage ownership migration, and safe switchover**.

---

# 2. Architectural Goals

## 2.1 Primary goal

Adding a new domain should require primarily:

- domain entities and business models
- domain-specific provider adapters
- domain normalization
- domain context construction
- domain scoring or decision logic
- domain prompts and schemas
- domain API routes
- domain tasks

It should **not** require creating another implementation of:

- RAG
- embeddings
- LLM transport
- evidence storage/attribution
- validation infrastructure
- entity resolution infrastructure
- pipeline orchestration
- generic scheduler

## 2.2 Secondary goals

The framework must also provide:

- strong domain isolation
- dependency injection and composition roots
- deterministic testability
- explicit degraded-state handling
- source-backed intelligence
- reproducible analysis metadata
- incremental migration from legacy implementations
- clear framework/domain persistence ownership

## 2.3 Non-goals

The framework does not attempt to make every domain semantically identical.

It does **not** require:

- universal scoring semantics
- universal recommendation vocabulary
- universal provider APIs
- universal context buckets
- universal business models

A generic framework should abstract mechanics, not erase domain meaning.

---

# 3. Core Architectural Principles

## 3.1 Framework owns intelligence mechanics

The framework owns reusable mechanisms such as:

```text
entity resolution
provider capability discovery
observation construction
provenance/evidence handling
embedding generation
vector persistence
RAG retrieval
LLM transport
structured-output recovery
validation mechanics
pipeline orchestration
```

## 3.2 Domains own intelligence semantics

A domain owns concepts such as:

```text
Stock:
- company
- ticker
- financial statement
- technical indicator
- investment score
- opportunity/risk semantics

HR:
- candidate
- employee
- job
- skills fit
- hiring recommendation
```

The framework should not branch on these concepts.

## 3.3 One source of truth per capability

Bad:

```text
intelligence/rag/
        ↓ copy
stock/rag.py
        ↓ copy
hr/rag.py
```

Good:

```text
intelligence/rag/
        │
        ├── generic retrieval mechanics
        │
        ├── Stock-specific context adapter
        └── HR-specific context adapter
```

A domain may specialize framework behavior, but must not fork framework mechanics.

## 3.4 Dependency direction

The dependency direction is:

```text
Domain ───────────────► Framework
Domain ───────────────► Shared

Framework ──X────────► Domain
Framework ──X────────► Stock-specific implementation
```

The framework must be usable with zero domain modules loaded.

This is enforced through source-level purity tests and isolated import tests.

## 3.5 Composition roots, not hidden dependencies

The generic pipeline answers **HOW**.

The domain composition root answers **WHAT implementation is used**.

Example:

```text
IntelligencePipeline()
    = minimal, domain-neutral, dependency-injected framework

build_stock_pipeline()
    = fully wired Stock production composition root
```

The pipeline must not import Stock classes.

---

# 4. Current Repository Architecture

The current framework is organized as follows:

```text
app/
├── core/                              # application/platform infrastructure
│   ├── config.py
│   ├── database.py
│   ├── logging.py
│   ├── observability.py
│   ├── redis_cache.py
│   ├── rate_limit.py
│   └── other platform infrastructure
│
├── intelligence/                     # domain-neutral intelligence framework
│   ├── contracts.py
│   ├── registry.py
│   ├── pipeline.py
│   ├── providers.py
│   ├── observations.py
│   ├── prompts.py
│   ├── entity_resolution.py
│   │
│   ├── rag/
│   │   ├── types.py
│   │   ├── filters.py
│   │   ├── ranking.py
│   │   ├── retrieval.py
│   │   └── service.py
│   │
│   ├── embeddings/
│   │   ├── types.py
│   │   ├── client.py
│   │   ├── batching.py
│   │   ├── persistence.py
│   │   └── service.py
│   │
│   ├── llm/
│   │   ├── structured_output.py
│   │   ├── client.py
│   │   └── __init__.py
│   │
│   ├── evidence/
│   │   └── ...
│   │
│   └── validation/
│       └── ...
│
├── shared/
│   └── entities.py                    # EntityRef, Observation, Evidence, etc.
│
├── workers/
│   └── scheduler.py                   # generic scheduler
│
├── domains/
│   ├── stock/
│   │   ├── manifest.py
│   │   ├── pipeline_factory.py
│   │   ├── config.py
│   │   ├── models/
│   │   ├── providers/
│   │   ├── ingestion/
│   │   ├── normalization/
│   │   ├── scoring/
│   │   ├── prompts/
│   │   ├── api/
│   │   └── workers/
│   │
│   ├── hr/                            # deferred / future domain
│   └── example/                       # framework-neutral example domain
│
└── main.py                            # app bootstrap + registry mounting
```

### Important distinction

Some Stock code still exists because the framework migration is intentionally incremental. Its presence does not mean the framework should depend on it.

The long-term target is that Stock retains only **Stock knowledge and domain integration glue**, while framework mechanics remain in `app/intelligence/`.

---

# 5. Domain Dependency Boundary

## 5.1 Allowed dependency

```text
app/domains/stock
        │
        ├── imports app.intelligence
        └── imports app.shared
```

## 5.2 Forbidden dependency

```text
app/intelligence
        │
        └── imports app.domains.stock    ❌
```

The framework must not contain:

```python
if domain == "stock":
    ...
```

or equivalent domain-specific branching.

This is enforced by source-level tests.

## 5.3 Clean import guarantee

The framework must be importable in a clean process with no domain packages loaded.

This proves domain-neutrality is not merely theoretical.

---

# 6. DomainModule Contract

The current `DomainModule` has **9 meaningful framework touchpoints**.

Conceptually:

```python
class DomainModule(Protocol):
    name: str
    version: str

    def get_api_router(...): ...
    def get_internal_router(...): ...
    def get_intelligence_tasks(...): ...
    def get_providers(...): ...
    def get_normalizers(...): ...
    def get_context_builder(...): ...
    def get_scoring_strategy(...): ...
    def get_prompts(...): ...
```

## 6.1 Why `get_models()`, `get_schemas()`, and `get_config()` were removed

They previously existed as catalog-like accessors but had no genuine framework-level consumer.

They were therefore removed instead of being artificially wired into the framework.

The rule is:

> **A contract method exists because the framework lifecycle requires it, not because a domain happens to have something useful to expose.**

## 6.2 Contract responsibilities

| Method | Framework role |
|---|---|
| `get_api_router()` | public domain API mounting |
| `get_internal_router()` | internal/domain operational API mounting |
| `get_intelligence_tasks()` | generic scheduler registration |
| `get_providers()` | domain capability source registration |
| `get_normalizers()` | domain normalization semantics |
| `get_context_builder()` | domain-specific context construction |
| `get_scoring_strategy()` | domain-specific decision/scoring behavior |
| `get_prompts()` | domain prompt registry |
| `name` / `version` | identity + reproducibility metadata |

---

# 7. Generic Intelligence Capabilities

## 7.1 Entity Resolution

Framework service:

```text
app/intelligence/entity_resolution.py
```

The framework owns:

- generic resolution lifecycle
- normalizer registration
- entity references
- normalization composition
- registration scoping

Domains own identifier semantics.

Stock, for example, registers ticker normalization.

The framework does not know what a ticker, CIK, ISIN, or CUSIP means.

---

# 8. Provider Capability Architecture

The provider architecture is capability-based.

The framework does **not** require every provider to implement one universal `fetch(EntityRef)` API.

Current conceptual capabilities:

```text
CapabilityProvider
├── EntityDataProvider
├── TimeSeriesProvider
├── NewsProvider
└── SearchProvider
```

## 8.1 Capability discovery

The framework can ask:

```python
framework_capabilities(provider)
has_capability(provider, "news")
```

Explicit provider capability declarations are authoritative.

Duck-typing is only a fallback for providers without explicit declarations.

This avoids a subtle bug where a shared adapter base accidentally caused every vendor to appear to implement every capability.

## 8.2 Stock provider adapters

Current Stock provider capability mapping:

| Provider | Capabilities |
|---|---|
| Massive | entity_data, time_series, news |
| FMP | entity_data, time_series |
| Finnhub | entity_data, time_series, news |
| SEC | entity_data, search |
| FRED | time_series |

The provider infrastructure remains domain/vendor-specific. Capability adapters expose a framework vocabulary without rewriting vendor implementations.

---

# 9. Observation Boundary

Providers should not push vendor-specific shapes directly throughout the framework.

The generic observation boundary is:

```text
External API
    ↓
Capability Adapter
    ↓
Observation
    ↓
Domain Normalizer
    ↓
Evidence
```

`Observation` is domain-neutral and includes fields such as:

```text
entity_ref
kind
source
observed_at
confidence
data
```

Example:

```text
Stock:
kind = quote
source = massive

HR:
kind = employee
source = workday
```

The framework does not need to know what those meanings are.

---

# 10. Evidence Architecture

Evidence is a first-class framework concept.

The preferred flow is:

```text
Observation
    ↓
observations_to_evidence()
    ↓
Evidence
    ↓
RAG / Context / LLM / Validation
```

The framework owns generic provenance and attribution mechanics.

Domains own the semantics of what constitutes meaningful evidence.

Stock may care about:

- financial statement evidence
- market news
- events
- investment claims

A future legal domain may care about:

- contracts
- court filings
- witness statements
- regulatory documents

The evidence mechanism remains shared.

---

# 11. Storage Ownership and Schema Boundaries

**This is a load-bearing architectural rule.**

The platform uses **Model A: framework-owned persistence for framework capabilities**.

## 11.1 Framework-owned persistence

Framework capabilities should use framework-owned shared persistence where the underlying concept has the same semantic meaning across domains.

Examples:

```text
embeddings
evidence
pipeline metadata
future shared intelligence infrastructure
```

These records should use generic identity such as:

```text
domain
entity_type
entity_id
metadata
```

rather than domain-specific fields such as:

```text
company_id
ticker
candidate_id
```

This is the persistence equivalent of `EntityRef`.

## 11.2 Domain-owned persistence

Domains own their business concepts.

Examples:

```text
Stock:
companies
stock_prices
financial_statements
market_events
company_news

HR:
candidates
employees
job_postings
interviews
```

The framework must not own these business schemas.

## 11.3 Injection versus ownership

Dependency injection does **not** determine schema ownership.

A generic persistence utility can receive a model as a dependency while the model remains framework-owned.

Example:

```python
PgVectorStore(
    model=Embedding,  # framework-owned capability model
    session=session,
)
```

The same generic persistence mechanism may receive a domain-owned model for legitimate domain business persistence.

Therefore:

> **Injection is an access pattern. Ownership is an architectural decision.**

## 11.4 Current migration state

Some framework capability persistence models originated inside Stock during the earlier migration.

For example, the current `Embedding` ORM ownership remains a legacy Stock location.

That is a migration artifact, not the target architecture.

The target is:

```text
app/intelligence/embeddings/
    └── framework-owned Embedding model/schema
```

with Stock consuming it through the generic persistence API.

This migration occurs only after the framework execution path is proven stable.

## 11.5 Domain extension data

A domain may need extra data attached to a shared framework record.

Three cases are allowed:

### Case A — Generic metadata is sufficient

Use the shared record's generic metadata.

### Case B — Domain-specific relational details are required

Use a domain-owned extension table that references the framework record.

Example:

```text
evidence
   │
   │ evidence_id
   ▼
legal_evidence_details
```

This table contains only Legal-specific information.

### Case C — The concept is genuinely generic

If the same semantic capability is required across domains, it belongs in the framework rather than creating domain-specific duplicates.

## 11.6 Forbidden shadow capabilities

Domains must not create parallel implementations of framework capabilities.

Examples:

```text
❌ hr_embeddings
❌ legal_embeddings
❌ hr_evidence
❌ stock_rag_documents
```

The issue is semantic ownership, not merely naming.

A legitimate extension such as:

```text
legal_evidence_details
```

is allowed because it references shared evidence rather than replacing it.

## 11.7 Migration ownership

Framework-owned schema changes are framework changes.

Domain migrations own domain business schemas.

A domain migration must not independently modify, duplicate, or drop framework-owned tables.

Framework schema evolution is allowed through the framework migration path.

## 11.8 Migration layout

The exact physical migration directory may remain centralized in Alembic.

The architecture requires **logical ownership**, not necessarily separate physical directories.

For example, a centralized Alembic graph can contain:

```text
001_framework_embeddings.py
002_stock_companies.py
003_stock_prices.py
004_framework_evidence.py
```

Each migration should clearly identify its owner.

## 11.9 Storage ownership verification

Storage ownership is an architectural invariant and is enforced in two stages.

### Stage 1 — deterministic source-level check

Maintain an explicit registry of framework-owned capability tables:

```python
FRAMEWORK_OWNED_TABLES = {
    "embeddings",
    "evidence",
}
```

The initial CI check statically inspects domain migration source and rejects `create_table`, `alter_table`, `drop_table`, or equivalent `op.*` operations targeting any table in `FRAMEWORK_OWNED_TABLES`.

This first-stage check is intentionally deterministic and cheap. It does **not** use wildcard naming heuristics such as `*_evidence`, because legitimate domain extension tables may contain the word `evidence` in their names.

Domain migrations must not independently modify framework-owned tables. Framework migrations may modify them.

### Raw SQL DDL rule

Domain migrations must not use raw SQL DDL through `op.execute(...)` to bypass the ownership check. Raw SQL DDL is prohibited in domain migrations unless an explicitly reviewed framework exception is added to the migration policy.

### Stage 2 — schema introspection hardening

Once migration tooling supports it, CI should additionally apply the complete migration graph to a scratch database and inspect the resulting schema through `information_schema` / PostgreSQL catalogs. The check should verify:

1. framework-owned tables exist with the expected structure and ownership
2. domain migrations did not create parallel implementations of framework capabilities
3. framework-owned schemas were not independently modified by a domain migration
4. shared foreign-key relationships are intact

Stage 2 is the long-term authoritative structural check; Stage 1 remains valuable as a fast pre-flight check.

# 12. Embeddings Architecture

Framework package:

```text
app/intelligence/embeddings/
├── types.py
├── client.py
├── batching.py
├── persistence.py
└── service.py
```

## Framework owns

- provider client abstraction
- batching
- retry/backoff
- batch fallback
- per-item isolation
- vector conversion
- dimension validation
- persistence mechanics
- deduplication

## Domain owns

- what should be embedded
- content extraction
- metadata semantics
- domain-specific document selection

Example:

```text
Stock
 ├── news
 ├── events
 ├── analyses
 └── filings

HR
 ├── candidates
 ├── jobs
 └── reviews
```

Both use the same generic embedding engine.

## 12.1 Embedding dimension policy

A shared `embeddings` table with a fixed pgvector dimension imposes a real platform constraint. `pgvector` vector columns have a fixed dimension such as `vector(3072)`.

### Current decision — platform-standard embedding profile

The platform adopts **one standard shared embedding profile for framework-owned embedding storage: 3072 dimensions**. The embedding model/provider may be centrally changed only through a controlled framework migration; domains do not independently choose incompatible dimensions for the shared store.

Consequences:

- every vector written to the shared embedding store must be 3072-dimensional
- domain code cannot select a different dimension for the shared framework store
- changing the platform-standard model/dimension requires controlled re-embedding/backfill
- the migration must include embedding-dimension validation and RAG/golden verification

This is a deliberate platform constraint chosen to preserve one shared embedding/RAG persistence model and keep cross-domain infrastructure simple.

### Future evolution

If multiple dimensions/models become a real platform requirement, the framework may introduce **framework-owned dimension/model partitions**. Such partitions remain framework infrastructure and are managed through framework migrations; domains still do not create or own parallel embedding capabilities.

### Prohibited outcome

```text
hr_embeddings
legal_embeddings
stock_embeddings
```

created as independently owned implementations of the framework embedding capability.

# 13. RAG Architecture

Framework package:

```text
app/intelligence/rag/
├── types.py
├── filters.py
├── ranking.py
├── retrieval.py
└── service.py
```

The framework owns:

- vector similarity search
- keyword retrieval
- hybrid retrieval
- metadata filtering
- date filtering
- threshold handling
- ranking
- deduplication
- pgvector query mechanics

Stock retains:

- news bucket semantics
- filing bucket semantics
- event bucket semantics
- previous-analysis semantics
- company/ticker meaning
- Stock-specific context enrichment

The relationship is:

```text
Generic RAG Core
       │
       ▼
Stock RAG adapter/context
       │
       ├── news
       ├── filings
       ├── events
       └── analyses
```

The generic RAG service must never acquire Stock-specific buckets internally.

---

# 14. LLM Architecture

Framework package:

```text
app/intelligence/llm/
├── structured_output.py
├── client.py
└── __init__.py
```

## Framework owns

- provider transport
- base URL handling
- client initialization
- timeouts
- SDK retries
- JSON-mode calls
- JSON recovery
- usage extraction
- common metadata

## Domain owns

- prompt content
- prompt version
- analysis types
- output schema
- domain-specific instructions
- domain validation semantics

This prevents a generic LLM client from knowing that one domain has an `investment_thesis` while another has a `candidate_summary`.

## Provider independence

The generic LLM layer should be usable with OpenAI-compatible providers such as:

- OpenAI
- Gemini-compatible endpoints
- Azure-compatible endpoints
- Ollama/vLLM or other OpenAI-compatible servers

Provider availability is an external dependency, not a framework architecture dependency.

---

# 15. Validation Architecture

Validation is split into:

## Generic validation

```text
schema validity
type validity
required fields
confidence bounds
result-envelope validity
structural consistency
```

## Domain validation

Stock-specific examples:

```text
investment analysis requirements
investment recommendation semantics
Stock evidence rules
```

The generic validation package must not contain:

```text
investment
portfolio
ticker
company-specific
```

This is enforced through source-level architecture tests.

---

# 16. Stock Composition Root

The Stock composition root is:

```text
app/domains/stock/pipeline_factory.py
```

Its responsibility is to assemble the generic framework with Stock implementations.

Conceptually:

```text
build_stock_pipeline()
        │
        ├── generic Entity Resolution
        ├── Stock RAG adapter
        ├── generic Evidence
        ├── generic Validation
        ├── Stock LLM service / generic LLM engine
        ├── Stock Context Builder
        └── Stock Scoring Strategy
                │
                ▼
        IntelligencePipeline
```

The pipeline itself does not import Stock.

This is the cleanest expression of the architectural boundary:

```text
pipeline.py = HOW
pipeline_factory.py = WHAT
```

---

# 17. IntelligencePipeline

The pipeline is the generic orchestration layer.

## 17.1 Current lifecycle

```text
1. Request
2. Resolve Domain
3. Resolve Entity
4. Ingest
5. Normalize
6. Collect Evidence
7. Retrieve RAG
8. Build Context
9. LLM Analysis
10. Validate
11. Score
12. Result
```

The current runtime stage set is represented in result metadata:

```text
entity_resolution
ingestion
normalization
evidence
rag
context
llm
validation
scoring
```

## 17.2 Stage semantics

Each stage can be:

```text
success
degraded
skipped
failed: <error>
```

The pipeline distinguishes hard failures from degradable optional failures.

## 17.3 Hard failure examples

Examples include:

- entity resolution crash
- context builder failure
- LLM service exception when LLM is required
- validator crash
- scoring execution failure

## 17.4 Degraded/skipped examples

Examples include:

- RAG service unavailable
- RAG returns empty context
- LLM not configured in a test environment
- optional provider unavailable
- incomplete source data

The rule is:

> **Do not silently swallow failures. Explicitly classify the stage and preserve enough metadata to understand what happened.**

---

# 18. AnalysisRequest and AnalysisResult

## 18.1 AnalysisRequest

The universal request language is:

```python
AnalysisRequest(
    entity_ref=EntityRef(
        domain="stock",
        entity_type="company",
        entity_id="AAPL",
    ),
    analysis_type="company",
)
```

The pipeline must not depend directly on:

```text
ticker
company_id
stock_id
candidate_id
```

Those are domain concepts.

## 18.2 AnalysisResult

The result envelope is generic.

It may include:

```text
status
score
confidence
recommendation
evidence
insights
risks
metadata
```

Domain-specific payloads remain inside domain-controlled insight/analysis fields.

Metadata should include reproducibility information such as:

```text
domain
domain version
pipeline version
LLM model
LLM provider
tokens used
prompt name
prompt version
analysis type
stage statuses
```

---

# 19. Versioning and Reproducibility

Versioning is required for trustworthy analysis provenance.

## 19.1 Domain version

`DomainModule.version` identifies the implementation version of the domain pack.

It is recorded in analysis metadata.

## 19.2 Pipeline version

`pipeline_version` identifies the framework orchestration version used to produce the analysis.

## 19.3 Prompt version

Prompt metadata should identify:

```text
prompt_name
prompt_version
analysis_type
```

## 19.4 Model metadata

LLM metadata should identify:

```text
provider
model
temperature
max_tokens
tokens_used
```

## 19.5 Compatibility policy

Current compatibility is enforced through:

- contract conformance
- framework tests
- domain integration tests
- golden comparisons

The registry does **not** currently reject arbitrary semantic-version differences.

A future compatibility matrix may introduce explicit major-version compatibility rules once external domains become independently versioned products.

---

# 20. Failure and Degradation Model

The system should preserve useful intelligence whenever evidence is partial.

Example: Stock with FMP free-plan limitations.

```text
Price data         ✓
News               ✓
Events             ✓
Technical          ✓
RAG                ✓
Financials         unavailable
Fundamental        degraded
LLM                still possible
```

A provider limitation should not automatically become a full pipeline failure.

The result should expose degraded stage state so downstream consumers can interpret confidence appropriately.

The system must distinguish:

```text
not available
failed
skipped
not configured
```

rather than mapping all of them to `None` or silently ignoring them.

---

# 21. Current Stock Architecture

Stock is currently the reference implementation.

Conceptually:

```text
POST /internal/analysis/company
        │
        ▼
   analysis worker
        │
        ▼
build_stock_pipeline()
        │
        ▼
IntelligencePipeline
        │
 ┌──────┼───────────────────────────────────────┐
 ▼      ▼        ▼       ▼       ▼       ▼       ▼
Resolve Provider Observe Evidence RAG Context LLM Validation Score
                                                   │
                                                   ▼
                                            Stock Strategy
                                                   │
                                                   ▼
                                           AnalysisResult
```

The old Stock orchestration remains available only as a reference/legacy comparison path until Phase 15/16 completes the migration.

---

# 22. Production Migration State

The migration is intentionally staged.

## Phase 1–10

Framework boundaries and Stock integration have been implemented.

## Phase 11

Golden equivalence was partially live-verified.

Scoring components were bit-identical between legacy and framework paths.

Live LLM equivalence was externally blocked by Gemini provider instability/quota.

## Phase 12

Framework hardening is complete.

Current test count:

```text
103/103 tests passing
```

The following are enforced:

- framework purity
- no domain imports in framework
- domain-neutral pipeline source
- evidence first-class usage
- validation neutrality
- deterministic Stock pipeline
- provider-independent LLM testing
- deterministic AAPL fixture

## Phase 13 — NEXT

Shadow Production.

The framework and legacy paths will run side-by-side while the legacy result remains authoritative.

## Phase 14

Live LLM equivalence when the provider is available.

## Phase 15

Framework storage ownership migration.

## Phase 16

Production switchover.

## Phase 17

Legacy cleanup.

---

# 23. Shadow Production

Shadow execution provides confidence without changing user-facing behavior.

Target flow:

```text
                     Analysis Request
                           │
                   ┌───────┴───────┐
                   ▼               ▼
               Legacy          Framework
                  │                │
                  ▼                ▼
               Result A         Result B
                   │                │
                   └───────┬────────┘
                           ▼
                       Comparator
                           │
                    metrics + logs
                           │
                           ▼
                    Legacy result
                    remains primary
```

## 23.1 Compare

Hard comparisons:

- score
- recommendation
- confidence bounds
- scoring components
- validation status
- failed pipeline stage

Structural comparisons:

- RAG structure
- evidence presence
- evidence source types
- LLM success
- stage states

Diagnostic comparisons:

- generated prose
- retrieval ordering
- token counts
- small floating-point differences

## 23.2 Shadow sampling

Shadow execution should be configurable.

Example:

```text
FRAMEWORK_SHADOW_ENABLED=true
FRAMEWORK_SHADOW_SAMPLE_RATE=0.10
```

Start small and increase as confidence grows.

Avoid accidentally doubling expensive provider/LLM calls for every request.

---

# 24. Deterministic Testing Strategy

The platform uses multiple verification levels.

## Level 1 — Pure framework tests

These validate generic mechanisms with no DB or network.

Current framework suite:

```text
103/103 passing
```

## Level 2 — Deterministic Stock pipeline

Uses:

- real Stock prompts
- real Stock validation
- real Stock scoring strategy
- fake deterministic LLM
- deterministic fixture data

No external LLM calls are required.

## Level 3 — Live golden verification

Uses:

- real database
- real provider data
- real framework path
- real legacy comparison path
- real LLM where quota/provider permits

## Golden terminology

Use the terms precisely:

```text
Reference implementation = current trusted Stock behavior
Reference case            = e.g. AAPL
Golden baseline            = stored expected result
Equivalence comparison    = legacy vs framework test
```

Avoid using "golden" as a synonym for all four concepts.

---

# 25. Golden Equivalence Criteria

The framework path must match the trusted Stock path semantically.

## Hard gates

- recommendation does not unexpectedly flip
- absolute score divergence is <= **0.5 points** (`abs(legacy.score - framework.score) <= 0.5`)
- confidence remains valid
- scoring components remain valid
- LLM/schema succeeds where required
- evidence does not unexpectedly disappear
- RAG structure remains intact
- pipeline stages do not unexpectedly fail

## Soft differences

- generated prose
- small retrieval-count changes due to live data movement
- floating-point rounding
- token counts
- ordering where semantically irrelevant

A successful equivalence test demonstrates that framework extraction did not change Stock business semantics.

---

# 26. Stock Reference Cases

The Stock verification matrix should use multiple cases:

| Ticker | Purpose |
|---|---|
| AAPL | primary complete reference case |
| NVDA | high-volume news / retrieval stress |
| MSFT | normal company execution |
| TSLA | additional normal company execution |
| SPY | benchmark/non-company semantics |
| SKHY | degraded-data behavior / FMP free-tier limitation |

SKHY is especially useful because it exercises partial-data behavior.

---

# 28. Storage Migration Verification

Storage changes must trigger a new equivalence cycle.

The correct sequence is:

```text
Pre-migration
   ↓
Shadow comparison
   ↓
Storage migration
   ↓
Schema verification
   ↓
Data backfill verification
   ↓
RAG verification
   ↓
Golden comparison again
```

This is mandatory because changing physical storage can change retrieval behavior even if application code remains unchanged.

The storage migration therefore cannot be considered safe merely because the migration itself succeeds.

---

# 29. Migration Path for Legacy Architecture

The platform migrated incrementally rather than through a rewrite.

General migration rule:

```text
Existing working behavior
        ↓
Characterization tests
        ↓
Extract generic mechanism
        ↓
Domain delegates to framework
        ↓
Golden comparison
        ↓
Production migration
        ↓
Legacy removal
```

Never:

```text
Delete working implementation
        ↓
Rewrite from scratch
        ↓
Hope behavior stays equivalent
```

---

# 30. Anti-Patterns

## 30.1 Copying framework services into domains

```text
❌ domains/hr/rag.py
❌ domains/hr/embeddings.py
❌ domains/hr/llm.py
```

unless the code is genuinely domain-specific and cannot belong in the framework.

## 30.2 Framework domain branches

```python
if domain == "stock":
    ...
```

Forbidden.

## 30.3 Universal provider pretending everything is fetch()

Do not force every provider into a single generic method if its capability model is different.

Use capability interfaces.

## 30.4 Domain-owned copies of framework persistence

```text
❌ hr_embeddings
❌ hr_evidence
```

## 30.5 Hidden provider failures

Avoid:

```python
except Exception:
    pass
```

Failures must be logged/classified.

## 30.6 Contract catalog growth without consumers

Do not add `DomainModule` methods simply because a domain has a useful object.

Every method must serve a framework lifecycle responsibility.

## 30.7 Framework coupling through type imports

A generic service must not import Stock ORM classes to discover schema details.

Use injection.

---

# 31. How to Extend the Platform with a New Domain

The new-domain workflow is deliberately **not copy-based**.

Do not:

```bash
cp -r app/domains/stock app/domains/legal
```

or copy an existing domain's intelligence services.

Instead create a new domain package deliberately.

## 31.1 Step 1 — Define the domain entity vocabulary

Choose:

```text
domain name
entity types
entity identifiers
analysis types
```

Example:

```text
legal
case
CASE-123
case_analysis
```

## 31.2 Step 2 — Define domain-owned business models

Create only the tables that represent domain business concepts.

Do not recreate framework capability tables.

## 31.3 Step 3 — Implement provider capabilities

Ask:

```text
What external capabilities does the domain need?
```

Then implement/adapt:

```text
EntityDataProvider
TimeSeriesProvider
NewsProvider
SearchProvider
```

only as needed.

## 31.4 Step 4 — Convert vendor data into observations

Provider output should become:

```text
Observation
```

with:

```text
EntityRef
kind
source
observed_at
confidence
data
```

## 31.5 Step 5 — Implement normalizers

Transform observations into domain-normalized semantics.

Do not push domain semantics into generic services.

## 31.6 Step 6 — Use generic evidence

Use framework evidence mechanisms for provenance and attribution.

Add a domain extension table only when generic metadata is insufficient.

## 31.7 Step 7 — Use the generic embedding service

Provide:

- text extraction
- metadata
- document/source selection

Do not build another embedding service.

## 31.8 Step 8 — Use the generic RAG engine

Define domain retrieval semantics such as:

```text
legal:
- cases
- contracts
- regulations
```

but do not recreate:

```text
vector search
ranking
filtering
deduplication
```

## 31.9 Step 9 — Provide a ContextBuilder

The domain transforms evidence + retrieved context into a domain-specific `IntelligenceContext`.

## 31.10 Step 10 — Provide prompts and schema

The domain defines:

- analysis type
- prompt
- prompt version
- output schema

The generic LLM service handles execution.

## 31.11 Step 11 — Provide domain scoring if needed

Implement `ScoringStrategy` only if the domain has a scoring/decision layer.

Scoring should remain domain-specific.

## 31.12 Step 12 — Add domain API

Expose only domain-owned endpoints.

## 31.13 Step 13 — Add domain tasks

Use `get_intelligence_tasks()` for domain-specific background work.

The scheduler remains generic.

## 31.14 Step 14 — Register the domain

Export a domain module/manifest discoverable by the registry.

## 31.15 Step 15 — Add tests before enabling production

Required levels:

```text
contract conformance
framework integration
unit tests
pipeline deterministic test
golden/semantic equivalence where applicable
```

---

# 32. AI Agent Rules for Platform Changes

AI agents working on this repository should follow these rules.

## Rule 1 — Identify the ownership boundary first

Before writing code, decide:

```text
framework capability?
domain knowledge?
domain business data?
shared infrastructure?
```

## Rule 2 — Never copy an intelligence service into a domain

Search `app/intelligence/` before creating:

```text
rag.py
embeddings.py
llm.py
evidence.py
validation.py
```

## Rule 3 — Never make framework code import a domain

If the framework needs something from Stock, inject it through an interface/factory.

## Rule 4 — Prefer composition over inheritance for domain assembly

Use:

```text
build_stock_pipeline()
```

rather than subclassing the entire pipeline for Stock.

## Rule 5 — Preserve the working Stock path during migration

Stock is the reference implementation.

Create characterization tests before replacing behavior.

## Rule 6 — Use deterministic tests when external providers are unavailable

Do not block architecture work on LLM quotas or external API availability.

## Rule 7 — Provider failure is not automatically pipeline failure

Classify the stage as degraded where appropriate.

## Rule 8 — Do not invent contract methods

A new interface belongs in the framework only if multiple domains or a genuine framework lifecycle require it.

## Rule 9 — Treat schema ownership as seriously as code ownership

Before adding a migration, ask:

```text
Is this business data?
Or am I recreating a framework capability?
```

## Rule 10 — Re-run golden tests after storage changes

Code equivalence is not enough when the persistence schema changes.

## Rule 11 — Do not use raw SQL to evade architecture constraints

Domain migrations must not bypass framework schema ownership checks through `op.execute()` or equivalent raw DDL.

## Rule 12 — Do not modify multiple architectural layers casually

A change that affects:

```text
framework code
+
storage schema
+
production orchestration
```

must be split into individually verifiable steps.

---

# 33. Testing and Architectural Invariants

Architecture should be enforced by executable tests where practical.

Current invariants include:

```text
framework has no static domain imports
pipeline has no domain-specific branches
pipeline uses EntityRef instead of Stock identifiers
pipeline does not construct Evidence directly
validation package contains no investment semantics
provider capability declarations are authoritative
Stock consumes generic RAG
Stock consumes generic embeddings
Stock consumes generic LLM mechanics
```

Future invariants should include:

```text
framework-owned table ownership
no shadow framework capability tables
no domain-owned duplicates of shared persistence
storage migration does not alter golden behavior
```

---

# 34. Verification Matrix

The project uses multiple forms of proof.

| Verification | Purpose |
|---|---|
| Pure framework tests | generic mechanics |
| Contract tests | domain/framework boundary |
| Source purity tests | architectural dependency direction |
| Deterministic Stock pipeline | end-to-end framework semantics without provider dependency |
| Live golden comparison | real DB/provider behavior |
| Shadow production | real operational equivalence |
| Performance comparison | abstraction overhead |
| Post-storage golden comparison | schema migration safety |

---

# 35. Current Test State

Current framework suite:

```text
103/103 tests passing
```

The testing stack includes:

### Level 1

Pure framework tests.

### Level 2

Deterministic Stock pipeline using real Stock prompts, validation, and scoring with a fake LLM.

### Level 3

Live legacy-vs-framework comparison using the real database and external providers.

Live LLM equivalence may be externally blocked by provider quota/availability and is tracked separately from framework correctness.

---

# 36. Operational Observability

Every pipeline stage records status.

Example:

```json
{
  "stages": {
    "entity_resolution": "success",
    "ingestion": "success",
    "normalization": "success",
    "evidence": "success",
    "rag": "success",
    "context": "success",
    "llm": "success",
    "validation": "success",
    "scoring": "success"
  }
}
```

A degraded run should make its degraded stage visible.

A failure should identify the exact stage rather than merely reporting "analysis failed".

---

# 37. Performance and Cost Considerations

Generic abstractions must not create unacceptable overhead.

Shadow production should measure:

- total latency
- provider call count
- DB query behavior
- embedding calls
- LLM calls
- memory usage

Because dual-running legacy and framework paths may double expensive external operations, shadow execution should support sampling.

The framework should avoid redundant fetching, embedding, or LLM work.

---

# 38. Roadmap

Current roadmap:

```text
Phase 1    Framework boundary                    ✅
Phase 2    Entity resolution                     ✅
Phase 3    Generic RAG                           ✅
Phase 4    Generic embeddings                    ✅
Phase 5    Provider capabilities                 ✅
Phase 5.5  Observation / evidence boundary      ✅
Phase 6    Evidence + validation                ✅
Phase 7    Generic LLM                          ✅
Phase 8    Stock framework integration          ✅
Phase 9    IntelligencePipeline activation      ✅
Phase 10   Stock pipeline factory               ✅
Phase 11   Golden equivalence                   ✅* 
Phase 12   Framework hardening                  ✅
Phase 13   Shadow Production                    NEXT
Phase 14   Live LLM equivalence                 PENDING
Phase 15   Framework storage ownership           PENDING
Phase 16   Production switchover                PENDING
Phase 17   Legacy cleanup                       PENDING
```

`*` Phase 11 remains marked with an asterisk because real live LLM equivalence was externally blocked by provider quota/availability, while the rest of the framework/Stock equivalence was verified.

---

# 39. Phase 13 — Shadow Production

The next operational step is:

```text
Legacy Path ───────────┐
                       ├── comparison
Framework Path ───────┘

Legacy result remains authoritative.
```

Recommended flow:

1. enable sampled framework shadowing
2. execute both paths
3. compare structured outputs
4. record comparison metrics
5. measure latency/cost
6. investigate divergences
7. progressively increase shadow sampling

No production switchover occurs during this phase.

---

# 40. Phase 14 — Live LLM Equivalence

When the external LLM provider is healthy:

1. run the same Stock analysis through both paths
2. verify prompt aliasing and schema validity
3. verify validator success
4. verify evidence attribution
5. verify scoring consistency
6. verify recommendation consistency
7. compare stage outcomes

The requirement is semantic equivalence, not byte-identical prose.

---

### Storage interaction

Phase 14 does not perform the storage ownership migration. Any storage change that affects embeddings, evidence, or RAG is revalidated by Phase 15 through the post-migration golden/equivalence checks.

# 41. Phase 15 — Framework Storage Ownership Migration

This is a dedicated architecture migration, not cleanup. It converts legacy framework-capability persistence into the ownership model defined in §11 without changing Stock intelligence semantics.

### Tasks

1. inventory current schemas
2. classify every table as framework-owned or domain-owned
3. apply the decided 3072-dimensional shared embedding policy
4. identify legacy framework-capability ORM models physically located under Stock
5. relocate framework capability ORM ownership into the framework while preserving generic dependency injection APIs
6. create/update framework migration revisions and classify migration ownership explicitly
7. preserve and backfill existing rows without losing provenance or generic `domain` / `entity_type` / `entity_id` identity
8. run Stage 1 migration ownership checks and Stage 2 scratch-DB schema introspection
9. verify post-migration RAG behavior against the pre-migration reference
10. rerun the complete Stock golden/equivalence matrix against post-migration storage
11. update architecture documentation, migration tests, and ownership invariants

### Exit criteria

- framework-owned tables are physically owned by the framework migration layer
- Stock business tables remain domain-owned
- generic persistence utilities still receive their dependencies through explicit injection
- existing embeddings/evidence retain their generic identity and provenance
- all shared vectors satisfy the 3072-dimensional framework invariant
- RAG behavior remains equivalent within the documented golden gates
- all framework and Stock regression tests pass

No domain should independently modify framework-owned schemas.

# 42. Phase 16 — Production Switchover

Only after:

```text
103/103 tests
+
deterministic Stock pipeline
+
shadow equivalence
+
live LLM equivalence
+
post-storage golden equivalence
```

Switch production from:

```text
legacy analysis orchestration
```

to:

```text
build_stock_pipeline()
        ↓
IntelligencePipeline
```

Keep the legacy implementation behind a rollback feature flag initially.

---

# 43. Phase 17 — Legacy Cleanup

Only after sustained production equivalence.

Remove:

- legacy orchestration
- compatibility shims
- duplicate framework mechanics
- obsolete Stock service wrappers
- old ownership locations for framework capability models
- temporary comparison paths

Do not delete working legacy code before the new production path has demonstrated stability.

---

# 44. Future Domains

HR and other domains are intentionally deferred until the Stock framework path is production-proven.

The framework will be considered genuinely generalized when a second domain can use:

```text
same Entity Resolution
same Providers framework
same Observation model
same Evidence
same Embeddings
same RAG
same LLM engine
same Validation
same IntelligencePipeline
```

without copying those implementations.

The first future domain should be intentionally small and serve as an architectural proof rather than a second large product.

---

# 45. Architecture Decision Records / Migration Lessons

Historical incidents belong here rather than in the core conceptual architecture.

Examples of lessons already discovered during migration:

- manifest accessors must return real implementations, not placeholder imports
- scoring strategies must delegate to actual production scoring behavior
- framework purity tests catch accidental domain leakage
- singleton state must be restored between tests
- SQLAlchemy async engines must not be accidentally reused across unrelated event loops
- prompt keys and analysis-type aliases must be explicitly aligned
- framework capability bases must not make undeclared provider capabilities appear supported
- generic persistence must not import domain ORM models
- architecture source-level tests are valuable because they catch structural regressions before runtime

These lessons explain why the current architecture emphasizes explicit contracts, composition roots, deterministic tests, and executable architectural invariants.

---

# 46. Final Architecture Statement

The platform should be understood as:

> **A reusable intelligence engine surrounded by pluggable domain packs.**

The framework provides the machinery:

```text
Entity Resolution
Provider Capabilities
Observations
Evidence
Embeddings
RAG
LLM
Validation
Pipeline
Registry
Scheduler
Shared Intelligence Storage
```

The domain provides the meaning:

```text
Entities
Providers / mappings
Normalizers
Context semantics
Scoring
Prompts
Schemas
Business models
Business rules
```

The dependency direction remains:

```text
Domain ───────────────► Framework

Framework ──X────────► Domain
```

The persistence direction follows the same principle:

```text
Framework capability
        ↓
Framework-owned persistence

Domain business concept
        ↓
Domain-owned persistence
```

And the operational migration strategy remains:

```text
Working legacy behavior
        ↓
Characterize
        ↓
Extract generic mechanism
        ↓
Framework + domain composition
        ↓
Deterministic verification
        ↓
Live equivalence
        ↓
Shadow production
        ↓
Storage ownership migration
        ↓
Production switchover
        ↓
Legacy removal
```

That is the architecture this project should preserve as it evolves.
