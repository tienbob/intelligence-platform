Yes. The two plans should be merged, but with one important structural change:

**the API and scheduled worker should both converge onto the framework path; neither should be treated as “legacy” just because its current implementation is legacy.**

Also, the checklist's Gate 2–6 terminology can stay, but the meaning of the migration needs to be corrected so that **“legacy” means legacy orchestration/engine, not the worker entry point**.

Here is the unified plan I would use as the master roadmap.

# PLAN — Unify Company Analysis Into One Shared Execution Core

> **Status:** IN PROGRESS
> **Started:** 2026-08-26
> **Goal:** Move all production company-analysis execution onto the framework path while preserving both production entry points — user-triggered API and scheduled worker — and migrate storage ownership to the target architecture.
> **Definition of Done:** Legacy analysis orchestration is gone, the framework execution path is the only production analysis engine, API and scheduled worker remain first-class entry points, storage ownership matches the target model, and every architecture-document claim is verifiably true against the running system.

---

# Target Architecture

The final production architecture is:

```text
                         Company Analysis
                                │
                ┌───────────────┴───────────────┐
                │                               │
          User API                         Scheduled Worker
                │                               │
          API wrapper                    Worker wrapper
                │                               │
                └───────────────┬───────────────┘
                                ▼
                    Framework Analysis Path
                                │
                    IntelligencePipeline
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
     Context/RAG             LLM Analysis          Scoring
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                ▼
                   Validation + Attribution
                                │
                                ▼
                     Canonical Persistence
                                │
                                ▼
                       Analysis + Artifacts
```

The critical distinction:

```text
PRODUCTION ENTRY POINTS

API ────────────────┐
                    ├──> framework path
Scheduled Worker ───┘
```

versus:

```text
LEGACY IMPLEMENTATION

old ContextBuilder
old LLM orchestration
old scoring orchestration
old persistence orchestration
        ↓
       REMOVE
```

The worker is **not removed**.

---

# Gate 0 — Known Bugs Closed

**Purpose:** Establish a clean baseline before architectural migration.

* [x] Stage-status bug fixed: ingestion/normalization report `degraded`/`failed` under real provider/normalizer exceptions.

  * Partial failure → `degraded` + completes.
  * All providers fail → hard failure.
  * Normalizer crash → `degraded` with raw observations preserved.
  * 5 tests + manual runtime verification.

* [x] `_evaluate_scores` no longer reports identical 1m/3m/6m forward returns when the horizon has not elapsed.

  * Returns `null`.
  * Logic extracted to `_forward_return_at_horizon`.
  * Regression tests pass.

* [x] `.env.example` corrected to:

  ```text
  EMBEDDING_DIMENSIONS=3072
  ```

* [x] `INTELLIGENCE_DOMAINS` explicitly configured.

  * No default discovery accidentally enabling HR.
  * Docker service defaults to `stock`.
  * `.env.example` documents allow-list.
  * Runtime verified.

* [x] Root README rewritten for v3.

  * No obsolete v2/placeholder claims.
  * Current production-legacy status accurately described.

* [x] Version labels disambiguated:

  * `application_version`
  * `architecture_version`
  * `pipeline_version`
  * `domain_version`
  * `scoring_version`
  * `prompt_version`

* [x] Purity test absolute path removed.

  * Uses derived repository root.
  * Works outside original machine.

* [x] `pytest-asyncio` loop-scope warning resolved.

  * Full suite produces zero warnings.

### Gate 0 exit condition

No known correctness defect from the existing baseline remains capable of invalidating the architectural migration.

---

# Gate 1 — Framework Correctness

**Purpose:** Prove the framework itself is trustworthy before making it production-primary.

* [x] Full test suite passes.

* [x] 114/114 tests passing.

* [x] Zero skipped/xfail hiding failures.

* [x] Framework purity test passes.

* [x] Clean subprocess import of `app.intelligence` succeeds with zero domain packages loaded.

* [x] Manual AAPL full-pipeline run completed successfully.

* [x] All 9 stages report real status.

* [x] Metadata includes:

  * prompt name
  * prompt version
  * LLM provider
  * LLM model
  * temperature
  * max tokens
  * tokens where available

* [x] Forced LLM failure verified:

  ```text
  run → failed
  llm → failed
  ```

* [x] Forced RAG-empty condition verified:

  ```text
  run → completed
  rag → degraded
  ```

* [x] Forced provider failure verified:

  ```text
  run → completed
  ingestion → degraded
  rag → skipped
  ```

* [x] Regression tests lock these semantics.

### Gate 1 exit condition

The framework path is demonstrably correct independently of the legacy implementation.

---

# Gate 2 — Phase 13: Shadow Production

**Purpose:** Compare the existing production engine against the framework while keeping the existing production result authoritative.

The important correction:

> **Shadowing compares the legacy orchestration against the framework. It does not classify the scheduled worker itself as legacy.**

During this phase:

```text
API
  │
  ├──> existing production analysis → returned to caller
  │
  └──> framework shadow → comparator

Worker
  │
  ├──> existing production analysis
  │
  └──> framework shadow → comparator
```

* [x] `FRAMEWORK_SHADOW_ENABLED` implemented.

* [x] `FRAMEWORK_SHADOW_SAMPLE_RATE` implemented.

* [x] Configuration verified.

* [x] Shadow execution is non-blocking.

* [x] Legacy/current production result remains authoritative.

* [x] Framework result cannot leak into production response.

* [x] Comparator persists one record per shadow execution.

* [x] Comparator stores:

  * score
  * recommendation
  * confidence
  * stage statuses
  * evidence presence
  * relevant divergence information

* [x] Low-rate sampling implemented.

* [x] Sustained live sampling performed.

* [x] Six-ticker reference matrix is not treated as sufficient by itself.

* [x] Hard-gate divergence rules established:

  * recommendation flip
  * score divergence > 0.5
  * invalid confidence
  * evidence disappearance
  * RAG structural difference
  * unexpected stage failure

* [x] Every unexplained hard-gate divergence investigated.

* [x] Sample rate progressively increased.

* [x] Divergence rate remains acceptable.

### Gate 2 exit condition

There are no unexplained production-significant differences between the current production analysis and the framework shadow path.

---

# Gate 3 — Phase 14: Live Framework Equivalence

**Purpose:** Establish that the framework can replace the current analysis engine.

This is where the **scheduled worker becomes particularly important**.

It is not merely an oracle because it is a real production path.

The comparison is:

```text
Existing scheduled-worker/API orchestration
                    │
                    ▼
             current result

Framework path
                    │
                    ▼
             framework result
```

* [x] Full live comparison for:

  * AAPL
  * NVDA
  * MSFT
  * TSLA
  * SPY
  * SKHY

  Result: **6/6 hard-gate PASS**, persisted at `scripts/gate3_report.json`
  (run log: `scripts/gate3_out.txt`).

* [x] Run with a healthy LLM provider.

  `gemini-3.5-flash`; llm stage `success` on all 12 legs.

* [x] No quota-blocked comparison.

* [x] SKHY explicitly verified:

  ```text
  fundamental → degraded
  analysis     → completes
  ```

  **Waived live** — provider free tier carries no SKHY statement data
  (provider limitation, not an app defect), so the run produced
  neutral-50 fundamentals with all stages `success`. The second half,
  `analysis → completes`, **was** proven live (`status=completed`,
  hard-gate PASS, score persisted). The `degraded` stage semantics are
  covered deterministically by `tests/framework/test_pipeline.py`
  (`test_partial_provider_failure_reports_degraded_not_success`,
  `test_rag_configured_but_empty_is_degraded`,
  `test_missing_llm_is_degraded_not_failed`).

* [x] Schema validity confirmed for every ticker.

* [x] Validator success confirmed.

  `validation` stage `success` on all six framework legs.

* [x] Evidence attribution confirmed.

  `evidence_attribution_count = 5` on every framework leg.

* [x] Recommendation consistency confirmed.

  legacy == framework recommendation for all six tickers.

* [x] Score validity confirmed.

  Framework `overall_score` exactly equals the legacy score on all six
  legs; DB rows present and scored.

* [x] RAG behavior confirmed.

  `rag` stage `success` ×6; claims backed by retrieved news sources.

* [x] Stage status semantics confirmed.

  Live run: all nine stages `success` ×6. Degraded / skipped / failed
  semantics covered deterministically by
  `tests/framework/test_pipeline.py`.

* [ ] Framework-generated prose manually reviewed for all six tickers.

  Summaries + risks for each ticker are captured in the `semantic`
  blocks of `scripts/gate3_report.json`, awaiting human review.

* [ ] Semantic equivalence signed off.

  Hard gates passed 6/6 with zero issues; awaiting explicit sign-off.

* [x] Byte-identical output explicitly **not** required.

  Equivalence is enforced at the contract level — scores,
  recommendations, schema validity, evidence attribution — while LLM
  prose naturally varies between engines/models.

### Gate 3 exit condition

The framework is behaviorally equivalent to the existing production analysis implementation for all domain-significant behavior.

---

# Gate 4 — Phase 15: Storage Ownership Migration

**Purpose:** Make persistence architecture match the target ownership model.

This is independent of whether the caller is API or worker.

## 4.1 Classify ownership

* [ ] Every existing table classified as:

  * framework-owned
  * domain-owned
  * explicitly shared, if such a category is genuinely required

* [ ] Ownership written down.

* [ ] No ownership inferred solely from current file location.

## 4.2 Embedding migration

* [ ] `Embedding` ORM moved to framework ownership.

* [ ] Stock consumes embeddings through framework contract/injection.

* [ ] Old Stock-owned references removed.

* [ ] Generic:

  ```text
  domain
  entity_type
  entity_id
  ```

  identity confirmed.

* [ ] Existing migrated rows spot-checked.

* [ ] Real production-like rows have correct identity fields.

* [ ] All embedding rows verified at 3072 dimensions.

* [ ] No silent truncation or dimensional mismatch.

## 4.3 Migration enforcement

* [ ] Stage 1 CI ownership guard implemented.
* [ ] `FRAMEWORK_OWNED_TABLES` deterministic guard works.
* [ ] Deliberately introduce an invalid domain migration.
* [ ] CI guard rejects it.
* [ ] Stage 2 schema-introspection check implemented.
* [ ] Run schema-introspection check against scratch DB.

## 4.4 Post-migration behavioral verification

* [ ] Re-run complete six-ticker Gate 3 matrix **after storage migration**.

* [ ] Confirm schema validity.

* [ ] Confirm scores.

* [ ] Confirm evidence attribution.

* [ ] Confirm recommendation.

* [ ] Confirm stage behavior.

* [ ] Confirm SKHY degradation semantics.

* [ ] RAG retrieval spot-check performed.

* [ ] Same query + same corpus produces equivalent ranked results before/after migration.

### Gate 4 exit condition

Storage ownership matches the target architecture without changing analysis behavior.

---

# Gate 5 — Phase 16: Production Switchover

**Purpose:** Make the framework the production analysis engine.

At this point:

```text
API ───────────────┐
                   ├──> framework path
Scheduled Worker ──┘
```

## 5.1 Feature flag

* [x] Implement:

  ```text
  ANALYSIS_ENGINE=legacy|framework
  ```

  * `app/domains/stock/config.py` (`ANALYSIS_ENGINE`, default `legacy`).
  * Single dispatch point reads the flag once for **both** entry points
    (`services/company_analysis.py::execute_company_analysis`).
  * Documented in root `.env.example`.
  * Default remains `legacy` until 5.2 switchover.

* [x] Test:

  ```text
  legacy → framework
  framework → legacy
  ```

  * `tests/test_engine_flag.py` flips the flag in both directions; 8/8 tests pass
    (flag tests + canonical analysis-contract tests + worker-persistence tests).

* [x] Verify both entry points respect the flag.

  * API (`api/analysis.py`) and worker (`workers/analysis_worker.py`) both route
    through `execute_company_analysis`; flipping `ANALYSIS_ENGINE` switches both
    simultaneously (asserted per entry point in `test_engine_flag.py`).
  * Framework path satisfies the canonical completed-analysis contract including
    all six domain snapshots (`macro_snapshot` now emitted by stock's ContextBuilder
    from fred observations); `domain_snapshots` flows through
    `AnalysisResult.metadata` into canonical persistence.

## 5.2 Switch production

* [ ] Switch production traffic to framework.
* [ ] API uses framework.
* [ ] Scheduled worker uses framework.
* [ ] No production caller receives legacy results after switchover.

## 5.3 Monitoring

Define an actual monitoring period before declaring success.

* [ ] Sustained monitoring period agreed upon: **[define days/weeks]**.

* [ ] Compare production behavior against Phase 13 shadow expectations.

* [ ] Monitor:

  * analysis failures
  * degraded runs
  * score distribution
  * recommendation changes
  * evidence attribution
  * RAG failures
  * embedding creation
  * latency
  * worker batch failures

* [ ] Zero unexplained production-significant divergence.

## 5.4 Rollback drill

* [ ] Deliberately switch:

  ```text
  framework → legacy
  ```
* [ ] Confirm production analysis still works.
* [ ] Switch:

  ```text
  legacy → framework
  ```
* [ ] Confirm framework remains healthy.

### Gate 5 exit condition

The framework is the actual production analysis engine for **both API and scheduled worker**.

The legacy implementation exists only as temporary rollback infrastructure.

---

# Gate 6 — Phase 17: Legacy Cleanup

**Purpose:** Remove the old engine without removing the production worker.

This distinction is critical.

## 6.1 Remove legacy orchestration

* [ ] Remove old `ContextBuilder` orchestration where it belongs exclusively to legacy analysis.

* [ ] Remove old `InvestmentScoringEngine` orchestration where superseded.

* [ ] Remove direct `LLMService` calls from:

  * `analysis.py`
  * `analysis_worker.py`
  * other legacy paths

* [ ] Search entire repository for old orchestration entry points.

* [ ] Confirm no production code can bypass framework analysis.

If compatibility wrappers remain:

> They must be thin compatibility adapters, not alternate implementations.

## 6.2 Preserve worker

* [ ] `analysis_worker.py` remains if it is the scheduled production entry point.

* [ ] Worker continues:

  * scheduling
  * ticker selection
  * batching
  * retries
  * per-ticker isolation
  * worker-specific logging

* [ ] Worker delegates analysis execution to framework.

* [ ] Worker contains no duplicate analysis engine.

Final worker architecture:

```text
Scheduled Worker
      │
      ├── scheduling
      ├── ticker selection
      ├── retry/batch semantics
      │
      └──> Framework Analysis Path
```

## 6.3 Remove shadow infrastructure

* [ ] Temporary shadow comparator removed.
* [ ] Temporary shadow flags removed or reduced to explicit opt-in diagnostics.
* [ ] Shadow-only database tables/data retention handled.

## 6.4 Remove old storage ownership

* [ ] Old Stock-owned `Embedding` references removed.
* [ ] Old migrations/docs removed or corrected.
* [ ] No code assumes Stock owns framework embeddings.
* [ ] No documentation claims Stock owns framework storage.

---

# Gate 7 — Documentation Truth Audit

This gate is deliberately separate from tests.

**Passing tests does not satisfy this gate.**

For every architecture-document claim:

```text
Claim
  ↓
Find implementation
  ↓
Find runtime evidence
  ↓
Verify behavior
  ↓
Mark true
```

* [ ] Read architecture document v3 from beginning to end.
* [ ] Check every §-numbered architectural claim.
* [ ] Check every ownership claim.
* [ ] Check every pipeline-stage claim.
* [ ] Check every version claim.
* [ ] Check every production-path claim.
* [ ] Check API behavior.
* [ ] Check worker behavior.
* [ ] Check framework behavior.
* [ ] Check storage ownership.
* [ ] Check migration status.
* [ ] Check configuration claims.
* [ ] Check deployment claims.
* [ ] Check failure/degradation semantics.

Explicitly eliminate stale terminology such as:

```text
legacy worker
worker will be retired
worker is temporary
worker exists only for comparison
```

Replace with the truthful model:

```text
scheduled worker = permanent production entry point
legacy = old analysis orchestration/engine
framework = canonical analysis engine
```

### Gate 7 exit condition

Every architecture-document statement can be demonstrated against the current running system.

---

# Gate 8 — Final Production Integrity Audit

This is the final technical gate.

## API

* [ ] `POST /internal/analysis/company` traced from request to persistence.
* [ ] Framework path confirmed.
* [ ] No legacy engine invocation.
* [ ] Correct HTTP lifecycle.
* [ ] Correct failure behavior.
* [ ] Correct persistence.

## Scheduled Worker

* [ ] Scheduled execution confirmed.
* [ ] Framework path confirmed.
* [ ] No legacy engine invocation.
* [ ] Multiple tickers tested.
* [ ] One ticker failure does not terminate the batch.
* [ ] Retry semantics confirmed.
* [ ] Daily score update confirmed.

## Analysis

* [ ] Score completeness verified.
* [ ] Recommendation verified.
* [ ] Confidence verified.
* [ ] Evidence attribution verified.
* [ ] RAG verified.
* [ ] Stage statuses verified.
* [ ] Provenance metadata verified.

## Storage

* [ ] Analysis rows correct.
* [ ] Embeddings correct.
* [ ] 3072 dimensions verified.
* [ ] Generic entity identity correct.
* [ ] Framework ownership verified.
* [ ] No duplicate persistence path.

---

# Gate 9 — Final Architecture Proof

The actual project completion test remains the strongest one:

* [ ] A fresh engineer/session with **no knowledge of this migration** reads only the architecture document.
* [ ] They run the test suite.
* [ ] They inspect the running system.
* [ ] They can correctly predict what:

  ```text
  POST /internal/analysis/company
  ```

  does in production.
* [ ] They can correctly explain what the scheduled worker does.
* [ ] They understand that both invoke the framework analysis engine.
* [ ] They correctly identify framework-owned vs domain-owned storage.
* [ ] They encounter zero undocumented surprises.

---

# Final Definition of Done

The project is complete only when all of these are true:

```text
                         ┌─────────────────┐
                         │   API           │
                         └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │                 │
                         │    Framework    │
                         │ Analysis Engine │
                         │                 │
                         └────────▲────────┘
                                  │
                         ┌────────┴────────┐
                         │ Scheduled      │
                         │ Worker         │
                         └────────────────┘
```

### Production architecture

* [ ] API is a permanent production entry point.
* [ ] Scheduled worker is a permanent production entry point.
* [ ] Both use the framework analysis engine.
* [ ] Neither contains a duplicate analysis implementation.

### Legacy removal

* [ ] Legacy orchestration removed.
* [ ] Legacy direct LLM/scoring/context execution removed.
* [ ] No hidden production path bypasses framework.
* [ ] Rollback code removed after confidence period.

### Framework

* [ ] Framework is the only production analysis engine.
* [ ] Pipeline statuses are correct.
* [ ] Attribution is correct.
* [ ] Scores are complete.
* [ ] RAG behavior is correct.
* [ ] Provenance is complete.

### Storage

* [ ] Framework-owned tables are actually framework-owned.
* [ ] Stock does not own framework embeddings.
* [ ] Embedding identity is generic.
* [ ] All embeddings are 3072-dimensional.
* [ ] CI prevents ownership regression.
* [ ] Post-migration behavior is verified.

### Verification

* [ ] Gate 3 equivalence passes.
* [ ] Gate 4 post-storage-migration matrix passes.
* [ ] Gate 5 production monitoring passes.
* [ ] Rollback drill passes.
* [ ] Documentation audit passes.
* [ ] Fresh-engineer prediction test passes.

---

## The one rule that should govern the entire roadmap

> **We are migrating the analysis engine, not migrating away from the worker.**

More precisely:

```text
API                  ─┐
                     ├──> Framework Analysis Engine
Scheduled Worker     ─┘
       ↑
       │
  permanent production
     entry point
```

while:

```text
Old ContextBuilder
Old scoring orchestration
Old direct LLM orchestration
Old persistence orchestration
        ↓
     LEGACY
        ↓
      DELETE
```

That resolves the apparent conflict between the two checklists: **Gate 3 compares against the scheduled-worker behavior because it is an important production oracle; Gate 5 moves that same worker onto the framework; Gate 6 removes its old orchestration, not the worker itself.**
