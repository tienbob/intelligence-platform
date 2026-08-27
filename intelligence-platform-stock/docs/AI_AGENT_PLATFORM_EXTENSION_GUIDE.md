# AI Agent Guide: Extending the Intelligence Platform with New Domains

**Document status:** Canonical implementation guide  
**Audience:** AI coding agents, senior engineers, architects, reviewers  
**Primary objective:** Add a new intelligence domain without duplicating framework capabilities or weakening the existing Stock platform.

---

# 1. Mission

You are extending an existing multi-domain intelligence platform.

The platform is designed around one rule:

> **The framework owns intelligence mechanics. A domain owns domain meaning.**

A new domain must reuse the existing framework for:

- entity resolution
- provider capabilities
- observations
- evidence and provenance
- embeddings
- RAG
- LLM transport and structured output
- validation
- orchestration
- registry/discovery
- scheduling

The new domain should own only the knowledge and behavior that are truly domain-specific:

- domain entities and identifiers
- provider mappings
- normalizers
- context semantics
- scoring strategy
- prompts
- domain schemas
- domain-specific validation/business rules
- domain API surface
- domain tasks

The goal is **not** to make every domain identical. The goal is to make the expensive intelligence infrastructure reusable while allowing domains to express different meanings and workflows.

---

# 2. Golden Rule for AI Agents

Before changing code, classify the requested change.

```text
                    Requested feature
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Generic mechanism            Domain meaning
             │                           │
             ▼                           ▼
      app/intelligence/            app/domains/<domain>/
```

Examples:

| Requirement | Correct location |
|---|---|
| Vector similarity search | `app/intelligence/rag/` |
| Embedding batching | `app/intelligence/embeddings/` |
| OpenAI-compatible LLM transport | `app/intelligence/llm/` |
| Evidence provenance | `app/intelligence/evidence/` |
| Generic JSON/schema validation | `app/intelligence/validation/` |
| Entity normalization mechanism | `app/intelligence/entity_resolution.py` |
| Provider capability discovery | `app/intelligence/providers.py` |
| Candidate identifier normalization | `app/domains/hr/` |
| Stock ticker semantics | `app/domains/stock/` |
| Investment score | `app/domains/stock/` |
| Candidate fit score | `app/domains/hr/` |
| Company news bucket semantics | `app/domains/stock/` |
| Employee review bucket semantics | `app/domains/hr/` |

**Never copy a framework service into a domain because the framework service does not know the domain semantics.** Add a domain adapter or domain policy instead.

---

# 3. Current Platform Architecture

The framework contains the reusable intelligence engine.

```text
app/
│
├── intelligence/
│   ├── contracts.py
│   ├── registry.py
│   ├── pipeline.py
│   ├── entity_resolution.py
│   ├── observations.py
│   ├── providers.py
│   ├── prompts.py
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
│   ├── evidence/
│   │   └── ...
│   │
│   ├── validation/
│   │   └── ...
│   │
│   └── llm/
│       ├── structured_output.py
│       ├── client.py
│       └── __init__.py
│
├── shared/
│   └── entities.py
│
├── workers/
│   └── scheduler.py
│
└── domains/
    ├── stock/
    │   ├── manifest.py
    │   ├── framework_path.py
    │   ├── pipeline_factory.py
    │   ├── providers/
    │   ├── normalization/
    │   ├── ingestion/
    │   ├── scoring/
    │   ├── api/
    │   └── ...
    │
    ├── hr/
    │   └── ...
    │
    └── example/
        └── ...
```

The exact file structure may evolve, but the dependency direction must not.

---

# 4. Dependency Direction

The most important architectural constraint is:

```text
Domain → Framework
Domain → Shared
Framework → Shared

NEVER:
Framework → Domain
```

Correct:

```python
# app/domains/hr/pipeline_factory.py
from app.intelligence.pipeline import IntelligencePipeline
```

Incorrect:

```python
# app/intelligence/rag/service.py
from app.domains.hr.models import Candidate
```

The framework must remain executable without any domain package.

This should remain true:

```python
IntelligencePipeline()
```

must be constructible without:

- a database
- a provider API key
- a Stock import
- an HR import
- a network request

---

# 5. DomainModule Contract

The domain plugs into the framework through `DomainModule`.

Current conceptual surface:

```python
class DomainModule(Protocol):
    name: str
    version: str

    def get_api_router(self) -> APIRouter: ...
    def get_internal_router(self) -> APIRouter: ...
    def get_intelligence_tasks(self) -> list[IntelligenceTask]: ...

    def get_providers(self) -> dict[str, Any]: ...
    def get_normalizers(self) -> dict[str, Any]: ...
    def get_context_builder(self) -> ContextBuilder: ...
    def get_scoring_strategy(self) -> ScoringStrategy: ...
    def get_prompts(self) -> PromptRegistry: ...
```

Do not add methods just because the domain happens to have a useful object.

A contract method should exist only when the framework lifecycle has a reason to consume it.

The framework should not contain convenience accessors merely to expose internal domain implementation details.

---

# 6. EntityRef: Universal Domain Language

Framework code should communicate about entities through `EntityRef` rather than domain-specific identifiers.

Example Stock:

```python
EntityRef(
    domain="stock",
    entity_type="company",
    entity_id="AAPL",
)
```

Example HR:

```python
EntityRef(
    domain="hr",
    entity_type="candidate",
    entity_id="candidate-123",
)
```

Example real estate:

```python
EntityRef(
    domain="real_estate",
    entity_type="property",
    entity_id="property-42",
)
```

Generic framework code should not branch on:

```python
if domain == "stock":
```

and should not expect:

```python
ticker
company_id
candidate_id
property_id
```

when the value is conceptually an entity reference.

## Domain-specific identifier semantics

Identifier interpretation belongs to the domain.

For example Stock can register a normalizer that turns:

```text
NASDAQ:AAPL
AAPL.US
 aapl 
```

into:

```text
AAPL
```

The framework provides the registration/execution mechanism; Stock provides the ticker semantics.

---

# 7. Provider Architecture

Providers are capability-based.

The framework already defines capabilities conceptually such as:

```text
EntityDataProvider
TimeSeriesProvider
NewsProvider
SearchProvider
```

Do not force every provider into a single `fetch(EntityRef)` interface.

A domain should declare the capabilities it needs.

Example HR provider catalog:

```text
WorkdayProvider
  └── EntityDataProvider

GreenhouseProvider
  ├── EntityDataProvider
  └── SearchProvider

HRAnalyticsProvider
  └── TimeSeriesProvider
```

## Provider adapter rule

Vendor infrastructure should stay in the vendor/domain layer.

For a new domain:

```text
External Vendor API
        ↓
existing vendor client
        ↓
thin capability adapter
        ↓
framework capability contract
        ↓
Observation
```

Do not duplicate:

- HTTP clients
- rate limiting
- caching
- circuit breakers
- vendor authentication
- vendor-specific pagination

inside `app/intelligence/`.

The framework should understand **capabilities**, not vendor APIs.

## Capability declaration rule

Explicit declarations are authoritative.

Do not infer a capability solely because a shared adapter base happens to expose a similarly named method.

This avoids false-positive capability discovery.

---

# 8. Observation Boundary

Provider responses enter the framework through domain-neutral `Observation` objects.

Conceptually:

```python
Observation(
    entity_ref=EntityRef(...),
    source="workday",
    observed_at=timestamp,
    kind="employee",
    confidence=0.98,
    data={...},
)
```

Stock example:

```text
kind = quote
source = massive
```

HR example:

```text
kind = employee
source = workday
```

The framework does not care what `kind` means.

The domain/provider adapter defines it.

## Provider → Observation rule

A vendor response should not be pushed directly into RAG or LLM context.

Use:

```text
Provider
  ↓
Observation
  ↓
Normalizer
  ↓
Evidence
```

This boundary provides a stable place for:

- source identity
- observed timestamp
- entity association
- normalization
- confidence
- provenance

---

# 9. Evidence Architecture

Evidence is the provenance layer between raw observations and intelligence reasoning.

Generic evidence should contain things conceptually equivalent to:

```text
entity_ref
source
source_id
observed_at
content/data
kind
confidence
provenance metadata
```

The framework owns:

- evidence identity
- provenance
- attribution
- generic deduplication
- evidence relationships
- persistence mechanics

The domain owns interpretation.

For example:

```text
Generic:
"This observation came from Workday at time T."

HR:
"This is an employee performance review."
```

Do not encode Stock or HR semantics into generic Evidence classes unless those semantics are truly universal.

---

# 10. Embedding Architecture

The generic embedding layer owns the mechanics:

- provider client
- batching
- retry/fallback
- vector conversion
- dimension validation
- persistence
- duplicate detection
- error isolation

The domain decides:

> **What should be embedded?**

For Stock:

```text
news
filings
events
analyses
```

For HR:

```text
candidate profile
resume
job description
performance review
employee profile
policy document
```

## Correct pattern

```text
HR domain
   ↓
construct document + metadata
   ↓
GenericEmbeddingService
   ↓
EmbeddingClient
   ↓
pgvector
```

## Incorrect pattern

```text
app/intelligence/embeddings/
    if entity_type == "candidate": ...
    if entity_type == "employee": ...
```

The generic service should never know what an employee is.

---

# 11. RAG Architecture

The generic RAG layer owns retrieval mechanics:

- vector similarity search
- keyword search
- filtering
- thresholding
- ranking
- deduplication
- hybrid search
- query embedding preparation

The domain owns retrieval semantics.

## Stock

Stock may define buckets such as:

```text
news
filings
events
analyses
```

## HR

HR may define:

```text
candidate_profiles
job_descriptions
interviews
performance_reviews
policies
```

The generic service must not contain code such as:

```python
retrieve_news()
retrieve_filings()
retrieve_candidates()
```

Those are domain concepts.

Instead the domain composes generic searches.

Conceptually:

```python
rag.search(
    query=...,
    filters=RetrievalFilters(...),
)
```

and the domain decides which searches to perform and how to interpret the results.

---

# 12. Context Builder

A Context Builder turns framework evidence/retrieval output into the context required by a domain analysis.

The framework should define the lifecycle:

```text
Evidence
   ↓
RAG results
   ↓
Context Builder
   ↓
Domain context
```

The domain owns the semantic composition.

Example Stock context:

```text
fundamentals
technical indicators
news
filings
events
previous analyses
market state
```

Example HR context:

```text
candidate profile
role requirements
experience
interviews
prior reviews
compensation constraints
```

The framework should only guarantee that the Context Builder receives structured inputs.

---

# 13. LLM Architecture

The generic LLM layer owns:

- provider transport
- OpenAI-compatible base URL handling
- model selection
- timeout/retry
- JSON mode
- JSON extraction/recovery
- token accounting
- metadata
- structured response mechanics

The domain owns:

- prompt content
- domain schema
- domain analysis type
- context semantics
- domain-specific validation

## Example

Generic:

```python
llm.analyze(
    prompt=prompt,
    schema=schema,
    context=context,
)
```

Stock schema:

```json
{
  "investment_thesis": "...",
  "bull_case": [],
  "bear_case": [],
  "catalysts": []
}
```

HR schema:

```json
{
  "candidate_summary": "...",
  "strengths": [],
  "risks": [],
  "recommendation": "..."
}
```

The generic LLM client must handle both without knowing what either field means.

---

# 14. Validation Architecture

Validation is two-layered.

## Generic validation

The framework owns:

- output parsing
- schema/type validation
- required field validation
- generic confidence bounds
- result envelope validation
- common structural invariants

## Domain validation

The domain owns:

- business rules
- semantic validity
- domain thresholds
- domain-specific claims
- scoring constraints

Example:

```text
Generic:
confidence ∈ [0, 1]

Stock:
recommendation must match investment score thresholds
```

The generic validator must not contain Stock-specific rules.

---

# 15. Scoring Strategy

Scoring is a domain capability.

The framework defines the contract, but it should not define the meaning of a score.

Stock:

```text
InvestmentScoringStrategy
    ↓
InvestmentScoringEngine
```

HR:

```text
CandidateScoringStrategy
    ↓
CandidateFitEngine
```

The strategy may consume framework outputs:

```text
entity
context
LLM result
quantitative evidence
```

but the scoring semantics belong to the domain.

## Important rule

Do not create a generic `UniversalScoringEngine` unless the scoring mechanics are demonstrably shared.

The framework should orchestrate scoring, not invent domain meaning.

---

# 16. Prompt Registry

Each domain owns its prompts.

Use `PromptRegistry` rather than hardcoding prompt selection into the pipeline.

Example:

```text
stock:
  company
  company_analysis
  market
  risk
  portfolio
```

A domain may register aliases when pipeline analysis types differ from prompt names.

Example:

```text
analysis_type = company
prompt = company_analysis
```

This mapping belongs in the domain manifest/registry configuration, **not inside the generic pipeline**.

---

# 17. IntelligencePipeline

The pipeline is domain-neutral orchestration.

Conceptual lifecycle:

```text
AnalysisRequest
      ↓
Resolve Domain
      ↓
Resolve Entity
      ↓
Ingest / Acquire Observations
      ↓
Normalize
      ↓
Collect Evidence
      ↓
RAG
      ↓
Build Context
      ↓
LLM
      ↓
Validate
      ↓
Score
      ↓
AnalysisResult
```

The pipeline must never contain domain conditionals like:

```python
if domain == "stock":
```

or:

```python
if entity_type == "candidate":
```

If a new domain requires a pipeline branch, first ask whether a contract or domain callback is missing.

## Pipeline dependency injection

The pipeline supports injectable services.

This provides two valid configurations:

### Framework/test configuration

```python
IntelligencePipeline()
```

Requirements:

- no database required to instantiate
- no API key required to instantiate
- no network call during construction
- no Stock imports

### Production domain configuration

Use a domain composition root such as:

```python
build_stock_pipeline()
```

or the equivalent for the new domain.

The composition root wires domain-specific implementations into the generic pipeline.

---

# 18. Domain Composition Root

Every serious domain should have one canonical construction point.

For example:

```text
app/domains/hr/pipeline_factory.py
```

Conceptually:

```python
build_hr_pipeline()
```

This factory should wire:

- domain registry/module
- entity resolution service
- domain RAG adapter/context
- generic embeddings where needed
- evidence
- validation
- domain LLM wrapper/prompt configuration
- domain scoring strategy

The pipeline factory is where domain-specific assembly belongs.

The generic pipeline must remain unaware of the domain.

---

# 19. API Integration

A domain should expose its API through the domain contract.

Typical structure:

```text
app/domains/hr/api/
    ...
```

The domain manifest exposes:

```python
get_api_router()
get_internal_router()
```

The framework/main application discovers and mounts these through the registry.

Do not modify `main.py` to add domain-specific routes manually.

Bad:

```python
from app.domains.hr.api import router
app.include_router(router)
```

Preferred:

```text
registry
  ↓
HR DomainModule
  ↓
get_api_router()
  ↓
main application
```

---

# 20. Background Tasks and Scheduler

Domain tasks should be declared through:

```python
get_intelligence_tasks()
```

The generic scheduler discovers tasks from registered domains.

Example HR tasks:

```text
refresh candidate profiles
refresh job postings
embed new candidate documents
recalculate candidate scores
```

The scheduler itself should not know what those tasks mean.

Do not create a new domain-specific scheduler unless the framework scheduler genuinely cannot represent the lifecycle.

---

# 21. Recommended New-Domain Structure

A new domain should start small.

Suggested structure:

```text
app/domains/<domain>/
│
├── manifest.py
├── pipeline_factory.py
│
├── api/
│   ├── routes.py
│   └── ...
│
├── providers/
│   ├── capabilities.py
│   ├── vendor_a.py
│   └── vendor_b.py
│
├── normalization/
│   ├── <entity>.py
│   └── ...
│
├── context/
│   └── builder.py
│
├── scoring/
│   └── strategy.py
│
├── prompts/
│   └── ...
│
└── workers/
    └── ...
```

Do **not** begin by creating:

```text
rag.py
embeddings.py
llm.py
evidence.py
validation.py
pipeline.py
```

If you feel you need one of those files, first determine whether the requirement belongs in the framework or is truly domain-specific.

---

# 22. Step-by-Step Procedure for an AI Agent

This is the recommended workflow whenever an AI coding agent is asked to add a new domain.

## Step 1 — Understand the domain

Write down:

```text
Domain name
Primary entity types
Identifiers
Analysis types
Provider sources
Expected outputs
Scoring concepts
Prompt types
```

Do not write code yet.

---

## Step 2 — Inspect existing framework capabilities

Before creating a new abstraction, inspect:

```text
app/intelligence/contracts.py
app/intelligence/entity_resolution.py
app/intelligence/providers.py
app/intelligence/observations.py
app/intelligence/evidence/
app/intelligence/validation/
app/intelligence/embeddings/
app/intelligence/rag/
app/intelligence/llm/
app/intelligence/pipeline.py
app/shared/entities.py
```

Ask:

> Can the existing framework already perform this function?

If yes, reuse it.

---

## Step 3 — Define EntityRef semantics

Choose:

```text
domain
entity_type
entity_id
```

Example:

```text
hr
candidate
candidate-123
```

Then implement the domain identifier normalizer and register it with entity resolution.

Test multiple input forms.

---

## Step 4 — Design provider capabilities

Create a table like:

| Provider | Capability | Required operation |
|---|---|---|
| Workday | entity_data | candidate lookup |
| Greenhouse | entity_data | job lookup |
| Greenhouse | search | candidate/job search |

Only declare capabilities that actually exist.

Implement thin adapters.

Do not rewrite provider infrastructure unnecessarily.

---

## Step 5 — Convert provider output to Observation

For every source:

```text
Vendor response
    ↓
Observation
```

Include:

- `EntityRef`
- source
- observed timestamp
- `kind`
- confidence when meaningful
- raw/normalized data

---

## Step 6 — Implement domain normalization

Normalize vendor-specific formats into the domain representation expected by the framework.

Examples:

```text
Workday employee schema
        ↓
HR observation
```

or:

```text
Greenhouse candidate schema
        ↓
HR candidate entity
```

Do not put vendor-specific normalization in generic framework modules.

---

## Step 7 — Decide what becomes evidence

Not every observation needs to become a retrieval document.

Define which observations are:

- evidence
- metadata only
- scoring input
- context-only
- embeddable

This is domain knowledge.

Use generic evidence infrastructure to persist/provide provenance.

---

## Step 8 — Define embedding documents

For each embeddable entity, define:

```text
content
metadata
entity_ref
source
published/observed timestamp
importance/confidence where relevant
```

Then delegate embedding mechanics to the framework.

Never write a second embedding client.

---

## Step 9 — Define RAG semantics

Choose the domain retrieval buckets.

Example HR:

```text
candidate
job
interview
review
policy
```

Implement a domain context/retrieval adapter that composes generic RAG calls.

Do not duplicate vector search SQL.

---

## Step 10 — Define context

Create the domain context builder.

Document exactly which inputs it consumes.

Example:

```text
Candidate Context
├── candidate profile
├── role requirements
├── experience evidence
├── interview summaries
├── relevant policies
└── previous candidate assessments
```

---

## Step 11 — Define scoring

Implement a domain `ScoringStrategy`.

Keep it independent from framework transport.

Example:

```text
Candidate fit score
├── skill match
├── experience
├── role alignment
└── interview evidence
```

Do not modify the generic pipeline to understand those concepts.

---

## Step 12 — Define prompts and schema

Register prompts with `PromptRegistry`.

Define domain-specific schemas.

Support aliases if `analysis_type` and prompt names differ.

Do not hardcode new prompt names inside the generic LLM service.

---

## Step 13 — Build the domain pipeline factory

Create:

```python
build_<domain>_pipeline()
```

It should compose the generic services with domain-specific adapters.

---

## Step 14 — Build domain integration tests

At minimum test:

```text
manifest
entity resolution
provider capabilities
observation creation
normalization
context builder
scoring strategy
prompt registry
pipeline factory
```

Use fakes where possible.

No live external API calls in unit tests.

---

## Step 15 — Create a deterministic golden scenario

A new domain should have a stable fixture.

Example:

```text
candidate_123_fixture.json
```

The fixture should contain deterministic:

- observations
- evidence
- RAG context
- fake LLM output

Then assert the final `AnalysisResult`.

This allows CI to validate the domain without depending on external APIs or LLM quotas.

---

## Step 16 — Test the framework path separately from live providers

Use three testing layers:

```text
Layer 1
Framework unit tests

Layer 2
Deterministic domain integration tests

Layer 3
Live provider / LLM verification
```

A provider outage must not prevent Layers 1–2 from running.

---

# 23. Testing Requirements for Every New Domain

A new domain is not complete until it has tests for:

## Contract tests

- domain discovery
- manifest shape
- router accessors
- task accessors
- provider catalog
- normalizers
- context builder
- scoring strategy
- prompts

## Entity tests

- valid identifiers
- alternative identifier formats
- whitespace/case normalization
- invalid identifiers
- entity-type scoping

## Provider tests

- capability declaration
- capability selection
- unsupported capability handling
- vendor response mapping
- provider health behavior

## Observation/evidence tests

- source attribution
- timestamps
- entity association
- confidence
- evidence construction

## RAG tests

- retrieval filters
- relevant documents
- ranking
- deduplication
- empty results
- malformed metadata

## Embedding tests

- dimensions
- batching
- fallback behavior
- persistence
- deduplication
- error isolation

## LLM tests

- prompt retrieval
- structured output
- malformed output
- schema validation
- token/metadata recording

## Pipeline tests

- happy path
- unknown domain
- missing provider
- degraded evidence
- LLM outage
- validation failure
- scoring failure
- stage attribution

## Golden test

A deterministic fixture must prove the end-to-end result.

---

# 24. AI Agent Anti-Patterns

## Anti-pattern 1 — Copying Stock services

Do not create:

```text
hr/rag.py
hr/embeddings.py
hr/llm.py
```

just because Stock has them.

First ask which parts are framework mechanics.

---

## Anti-pattern 2 — Generic framework knows domain names

Never add:

```python
if domain == "stock":
```

or:

```python
if entity_type == "candidate":
```

inside generic services.

---

## Anti-pattern 3 — Provider-specific logic in framework code

Don't add FMP/Massive/Workday logic to `app/intelligence/`.

---

## Anti-pattern 4 — New universal abstractions without evidence

Do not create:

```text
UniversalScoreEngine
UniversalEntityModel
UniversalDomainSchema
```

unless several domains demonstrate a truly shared need.

---

## Anti-pattern 5 — Changing domain behavior during extraction

When generalizing Stock behavior, preserve Stock semantics.

First extract.

Then prove equivalence.

Only then improve behavior separately.

---

## Anti-pattern 6 — Live API calls in unit tests

Never make the framework test suite depend on:

- Gemini quota
- OpenAI quota
- Massive availability
- FMP subscription
- SEC availability

Use fakes for deterministic tests.

---

## Anti-pattern 7 — Swallowing failures

Don't write:

```python
except Exception:
    pass
```

The framework should distinguish:

```text
success
skipped
degraded
failed
```

and preserve stage attribution.

---

# 25. Failure Semantics for New Domains

Every domain must agree with the framework's distinction between hard failure and degradation.

## Hard failure

Examples:

```text
entity resolution crash
context builder crash
validation crash
scoring crash
required LLM failure
```

These should stop the analysis.

## Degraded execution

Examples:

```text
optional provider unavailable
missing optional source
empty RAG result
partial source history
provider subscription limitation
```

These may allow the analysis to continue, but the result should expose the degraded state.

This is important for trust.

A domain should not silently turn:

```text
no evidence
```

into:

```text
strong confidence
```

---

# 26. Result Contract

A domain should return the generic `AnalysisResult` envelope.

The envelope should carry generic information such as:

```text
status
score
confidence
recommendation
insights
risks
evidence
metadata
stage statuses
provenance
```

Domain-specific content belongs inside structured domain payloads or typed insight structures.

Example Stock:

```text
investment thesis
bull case
bear case
catalysts
```

Example HR:

```text
candidate summary
strengths
risks
recommendation rationale
```

Do not redesign the envelope for every domain unless the envelope truly cannot represent a generic intelligence result.

---

# 27. Migration Strategy for Existing Domains

If an existing domain already contains duplicated services, follow this order:

```text
1. Identify production implementation
2. Characterize behavior
3. Identify generic mechanics
4. Extract framework core
5. Make domain delegate to framework
6. Run domain regression tests
7. Compare golden results
8. Remove obsolete duplicate code
```

Never start with deletion.

The production domain is the oracle.

---

# 28. How to Judge Whether Something Belongs in the Framework

Ask these questions in order:

### Question 1
Would two unrelated domains plausibly need this behavior?

If no → domain.

### Question 2
Does the behavior depend on domain vocabulary?

If yes → probably domain.

### Question 3
Can the behavior operate using `EntityRef`, `Observation`, `Evidence`, metadata, or generic contracts?

If yes → framework candidate.

### Question 4
Would making it generic force awkward conditionals for multiple domains?

If yes → abstraction may be premature.

### Question 5
Can you write a domain-neutral test without Stock/HR imports?

If yes → strong framework candidate.

---

# 29. Definition of a Successful New Domain

A new domain is considered successfully integrated when:

```text
✅ Domain discovered by registry
✅ Manifest conforms to contract
✅ API routers mount through framework
✅ Internal router mounts through framework
✅ Tasks register through generic scheduler
✅ EntityRef works
✅ Entity normalization works
✅ Providers expose explicit capabilities
✅ Provider output becomes Observation
✅ Observation becomes Evidence
✅ Evidence can be embedded
✅ RAG can retrieve domain data
✅ Context Builder creates domain context
✅ Generic LLM produces structured output
✅ Domain validation succeeds
✅ Domain scoring succeeds
✅ IntelligencePipeline completes
✅ AnalysisResult is valid
✅ Deterministic golden test passes
✅ No framework code imports the domain
✅ No copied RAG/embedding/LLM infrastructure exists
```

That is the actual completion standard.

---

# 30. Definition of Platform Success

The platform is successful when an AI agent can be given:

> "Add a new domain for X."

and the resulting implementation primarily consists of:

```text
DomainModule
Providers
Normalizers
Context Builder
Scoring Strategy
Prompts
Schemas
API
Tasks
```

instead of:

```text
X/rag.py
X/embeddings.py
X/llm.py
X/evidence.py
X/validation.py
X/entity_resolution.py
X/pipeline.py
```

The strongest possible proof is:

```text
                    ONE PLATFORM
                         │
          ┌──────────────┴──────────────┐
          │                             │
        Stock                           HR
          │                             │
   Investment Analysis           Candidate Analysis
          │                             │
          └──────────────┬──────────────┘
                         │
                  Same Intelligence
                       Framework
```

The framework supplies the machinery.

Each domain supplies the meaning.

---

# 31. Final Checklist for an AI Coding Agent

Before opening a PR for a new domain, confirm every item:

```text
[ ] I read app/intelligence/contracts.py
[ ] I read app/intelligence/pipeline.py
[ ] I inspected existing framework services before adding new ones
[ ] I defined EntityRef semantics
[ ] I registered identifier normalizers
[ ] I mapped provider capabilities
[ ] I used thin provider adapters
[ ] I created Observation objects
[ ] I used generic Evidence infrastructure
[ ] I used GenericEmbeddingService
[ ] I used GenericRAGService
[ ] I used the generic LLM client
[ ] I used PromptRegistry
[ ] I implemented domain-specific ContextBuilder behavior
[ ] I implemented a domain ScoringStrategy
[ ] I created a domain pipeline factory
[ ] I did not add domain branches to app/intelligence/
[ ] I did not copy Stock services
[ ] I did not add live network calls to unit tests
[ ] I added deterministic framework/domain tests
[ ] I added a golden test
[ ] I verified degraded-provider behavior
[ ] I verified hard-failure behavior
[ ] I verified registry discovery
[ ] I verified API/internal router registration
[ ] I verified scheduler task registration
[ ] I verified AnalysisResult structure
[ ] I verified the framework can execute without the new domain
[ ] I checked for duplicate generic mechanics
```

If any item is false, the domain is not ready to be considered complete.

---

# 32. Final Instruction to AI Agents

When extending this platform, optimize for **reusability without abstraction theater**.

Do not ask:

> "How do I copy the Stock implementation for this new domain?"

Ask:

> **"Which parts of the Stock implementation are intelligence mechanics, which parts are domain knowledge, and how can I reuse the mechanics while preserving the domain semantics?"**

The correct architecture is:

```text
Domain knowledge
      ↓
Domain adapters
      ↓
Generic intelligence capabilities
      ↓
Generic pipeline
      ↓
Domain result
```

The incorrect architecture is:

```text
Stock implementation
      ↓ copy
New domain implementation
      ↓ copy again
Third domain implementation
```

Every new domain should make the platform **more reusable**, not create another fork.

**When in doubt: reuse the framework, isolate domain semantics, preserve behavior, add tests, and never introduce a framework dependency on a specific domain.**
