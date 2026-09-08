# Plan - Analysis Integrity and Response Contract

> Status: Proposed
> Date: 2026-09-03
> Scope: Framework company analysis after the Gate 6 migration

## Objective

Make the framework analysis trustworthy and legacy-compatible in information
surface without copying legacy data or scoring defects.

The legacy result is an information-shape oracle only. Canonical normalized
data, deterministic scoring, and validated evidence are the correctness
sources.

## Target Architecture

```text
Providers
  -> canonical normalization
  -> snapshots and scoring
  -> RAG retrieval
  -> LLM analysis
  -> claim validation and evidence attribution
  -> complete AnalysisResult contract
  -> persistence and API serialization
```

## Ordered Work Plan

### 1. Define and implement the canonical response contract

- Define the canonical `AnalysisResponse` schema before changing downstream
  producers.
- Preserve these top-level sections:
  - `analysis_id`, `status`, `ticker`
  - `investment_score`, `risk_score`, `confidence`
  - `confidence_breakdown`
  - `analysis`
  - `snapshots`
  - `rag_context`
  - `evidence`
  - `recommendation`
  - `created_at`
- Preserve the useful legacy information surface without reproducing legacy
  bugs.
- Require complete snapshot groups:
  - `market`
  - `technical`
  - `fundamental`
  - `news`
  - `events`
  - `macro`
  - `risk`
- Preserve recommendation fields: reasons, risks, invalidating conditions,
  and recommended weight.
- Ensure persistence and Pydantic serialization do not silently drop fields.

Exit criteria:

- A contract test can construct a complete response and round-trip it through
  persistence and the API schema.
- Placeholder-only snapshots are rejected for completed analyses.

### 2. Fix fundamental normalization and period alignment

- Trace SEC and FMP statement adapters through normalization into snapshots.
- Select one coherent reporting period for revenue, net income, margins,
  cash flow, debt, and ratios.
- Populate `fundamental_snapshot.metrics` and
  `fundamental_snapshot.latest_statement` consistently.
- Keep raw provider values and canonical derived values distinguishable.
- Validate derived margins and growth rates against their source values.
- Record the source period and provider for every canonical fundamental set.

Exit criteria:

- Revenue, net income, and net margin are mathematically consistent.
- No LLM or API field can present values from different periods as one set.
- Missing data is represented as unavailable, not as a neutral fallback.

### 3. Fix market and quote normalization

- Treat provider volume `0` as unavailable unless the provider explicitly
  documents zero as valid.
- Fall back to the latest valid persisted volume when appropriate.
- Preserve latest price, timestamp, one-day change, 30-day high/low, and
  30-day average volume.
- Track the provider and freshness of each market metric.

Exit criteria:

- Invalid zero volume does not overwrite valid historical volume.
- Market snapshot values have a consistent timestamp and source.

### 4. Enforce company-scoped news and event data

- Audit `CompanyNews` links and provider ticker metadata.
- Require company ID or verified ticker/entity matching before including an
  item in company snapshots, RAG, or evidence.
- Exclude broad market, ETF, and unrelated-company articles unless their
  relevance is explicitly represented by a validated relation.
- Apply the same scope policy to live observations and persisted records.

Exit criteria:

- Mixed-company fixtures include only records relevant to the requested
  company.
- Snapshot and RAG counts reflect filtered records, not raw provider counts.

### 5. Enforce referential evidence identity

- Define evidence identity as the tuple
  `entity_type + entity_id`, not numeric equality with `source_id`.
- Resolve every evidence item to the exact source record.
- Verify that provider IDs and metadata describe that same record.
- Reject or mark inconsistent records as invalid rather than silently
  attributing them to another source.

Valid example:

```text
entity_type = news
entity_id   = 45
source_id   = news_45
```

Invalid example:

```text
entity_type = news
entity_id   = 44
source_id   = news_45
```

Exit criteria:

- Every evidence item resolves to one source record.
- Evidence tests cover mismatched database IDs, provider IDs, and metadata.

### 6. Define macro ingestion and freshness semantics

- Distinguish provider success, fetched points, inserted rows, duplicates,
  and failures.
- Treat `inserted = 0` with all points duplicated as successful ingestion.
- Add `latest_observed_at`, `latest_db_value_at`, and freshness status to the
  macro snapshot or its metadata.
- Make stale values visible to consumers instead of presenting them as
  current.

Target metadata:

```json
{
  "provider_status": "success",
  "fetched": 50,
  "inserted": 0,
  "duplicates": 50,
  "latest_observed_at": "2026-09-03T07:42:00Z",
  "latest_db_value_at": "2026-09-03T07:42:00Z",
  "fresh": true
}
```

Exit criteria:

- Duplicate-only ingestion is not reported as a failure.
- Stale, unavailable, duplicate-only, and fresh states are distinguishable.

### 7. Validate LLM claims against canonical data

- Run claim validation after canonical snapshots and evidence are built.
- Resolve each numeric or factual claim to canonical evidence where possible.
- Classify claims as `supported`, `conflicting`, or `unsupported`.
- Preserve the original claim, expected canonical value, source, and diagnostic.
- Prevent conflicting claims from being presented as verified facts.
- Include validation status in the persisted analysis and API response.

Example:

```json
{
  "claim": "Apple generated $3.5B net income",
  "status": "conflicting",
  "expected": 29800000000,
  "source": "SEC",
  "diagnostic": "Claim conflicts with the canonical fundamental snapshot"
}
```

Exit criteria:

- A claim cannot be marked source-backed without valid evidence attribution.
- Numeric claims outside the configured tolerance are flagged.
- Claim validation never changes deterministic scoring inputs.

### 8. Complete response-shape restoration

- Wire all canonical snapshots into `domain_snapshots`.
- Persist event snapshots even though they are not currently first-class
  database columns, or add the required schema migration if queryability is
  required.
- Persist full RAG buckets and evidence metadata in the analysis context.
- Preserve confidence breakdown values generated by Python.
- Populate recommendation details from validated analysis output and the
  deterministic score row.
- Remove placeholder notes when actual metrics are available.

Exit criteria:

- A fresh response contains the complete contract without requiring clients
  to reverse-engineer scoring or persistence internals.

### 9. Contract and data-quality test suite

Add focused tests for:

- Response schema round-trip and required sections.
- Full market and technical metrics.
- Fundamental period alignment and margin arithmetic.
- Zero-volume quote handling.
- Mixed-company news/event filtering.
- Referential evidence identity.
- Macro duplicate and freshness states.
- Supported, conflicting, and unsupported LLM claims.
- Persistence and API serialization without field loss.

### 10. Fresh production validation

- Rebuild the Python service.
- Run unit, framework, persistence, and API contract tests.
- Execute fresh AAPL and a second ticker analysis.
- Inspect provider, ingestion, RAG, claim-validation, and persistence logs.
- Compare the result to the legacy payload for information coverage only.
- Confirm that canonical values, scoring, and evidence remain independent of
  legacy output.

## Definition of Done

- The API returns the complete canonical response contract.
- All completed snapshots contain actual metrics or explicit availability status.
- Fundamental values are period-aligned and **mathematically consistent**
  (e.g. `net_margin = net_income / revenue`, `revenue_growth_yoy` measured
  against the year-ago quarter, not the preceding quarter).
- Market changes and derived percentages are internally consistent
  (`price_change_1d_pct` and `price_change_1d` derive from the same fields).
- News and events are **company-scoped** (verified company_id / ticker /
  provider relationship first; controlled textual relevance only as a
  fallback).
- Every evidence reference resolves to an exact source record.
- Macro freshness is explicit.
- **SEC/financial evidence is retrievable through RAG** (filing ingestion +
  embedding + retrieval) — required for financial-claim auditability.
- Every factual LLM claim is **supported, explicitly inferred, or rejected**;
  claim validation distinguishes `available` / `unavailable` /
  `insufficient` / `conflicting` evidence status.
- **Conflicting claims cannot enter the verified analysis.**
- **The deterministic recommendation is authoritative and cannot be
  contradicted by the LLM** — a conflict surfaces a validation issue.
- The LLM narrative cannot modify deterministic scoring inputs.
- The framework remains the only production analysis engine.
- Focused and end-to-end contract tests pass, including cross-field
  consistency invariants.

---

## Appendix A — External Validation Feedback Triage (NVDA Q2 FY2027, 2026-09-04)

Verification of the reported findings against the framework implementation.

| # | Finding | Verdict | Code location / disposition |
|---|---------|---------|------------------------------|
| 1 | `revenue_growth_yoy: 0.179` is QoQ mislabeled as YoY | ✅ **Confirmed** | `StockContextBuilder._build_fundamental_snapshot` used `rows[1]` (immediately preceding quarter) as the comparison. **Fixed**: `_year_ago_row_for()` matches the same quarter ≈1 year prior (date + period_type); omits the metric when no comparable exists instead of mislabeling QoQ. Also fixed `_score_growth_snapshot` `x or y` falsy-zero bug. |
| 2 | Claim validation is diagnostic, not a gate | ✅ **Confirmed** | Pipeline only appended `claim_validation`; output still carried unsupported claims, and `_validation.status` stayed `"valid"`. **Fixed**: `_validate_output` now reports `valid_with_evidence_issues` + `claims_analyzed`/`claims_unsupported`; each claim carries an `evidence_status` of `available` / `unavailable` / `insufficient` (`conflicting` reserved for domain-level semantic checks); prompt rule #7 requires inferences to be labeled and unsupported claims to be excluded from synthesis. |
| 3 | `source_backed_claims` always empty despite evidence | ✅ **Confirmed** | Prompt schema gave `source_backed_claims` a `source` object but the validator only accepted `evidence_ids`, so every item was marked unsupported and filtered out before persistence. **Fixed**: prompt example now includes `evidence_ids`; `_run_llm` accepts a canonical `source` block as an alternative legitimate backing for `source_backed_claims`. |
| 4 | `news_snapshot` contaminated with global news | ✅ **Confirmed** | `_company_observations` passed through ALL items when none carried `tickers` (global-feed fallback). **Fixed**: untagged items must now match ticker or company-name token in title/summary/content; tagged items must match ticker. |
| 5 | RAG evidence surface too narrow (news only) | ✅ **Confirmed & Fixed** | Root causes: (a) `_belongs_to_company` requires `company_id` metadata — corpus items missing it are dropped; (b) `embed_all()` had no `sec_filing` path, so the `filings` bucket could never return results. **Fixed**: new `SecFiling` canonical model stores human-readable text chunks derived from SEC XBRL facts (one chunk per company/fiscal-year/period/form); `_build_filing_chunks()` converts XBRL facts to readable chunks during ingestion; `embed_sec_filings()` embeds them with `company_id`/`ticker`/`filing_type` metadata; wired into `embed_all()` and the scheduler (`Ingest SEC filings` task). The existing `retrieve_filings()` RAG method now returns filing evidence so financial claims are auditable against the primary source. |
| 6 | Vera CPU "$20B revenue by 2026" overreach | ⚠️ Output-level | Prompt rules #8/#9 added (attribute forward-looking language verbatim; label inferences). No code enforcement of semantics. |
| 7 | China <1% over-generalization | ⚠️ Output-level | Same prompt guardrails; the exact disclosure must be reproduced. |
| 8 | `price_change_1d` vs `price_change_1d_pct` inconsistent | ✅ **Confirmed** | Observed path trusted provider `change_percent` (0) while persisted path computed a ratio from closes. **Fixed**: `_canonical_change_facts()` derives ratio and percent from the same fields; zero/absent change → unavailable (never overwrites a deterministic persisted value). |
| 9 | `drawdown` vs `max_drawdown` differ | ⚠️ By design, undocumented | Technical `drawdown` uses 365d window; risk `max_drawdown` uses 252d. Schema does not carry the metric window. Documented; schema-level `value/period/method` object is a future contract change (§2). |
| 10 | `fundamental_risk: null` | ✅ **Confirmed** | `RiskEngine._fundamental_risk` reads the persisted `FinancialStatement` table; when the analysis was produced from provider observations (no persisted statements) it returns `None`, yet the risk score is presented as a full company risk score. Documented; requires FinancialStatement persistence parity. |
| 11 | LLM "high-conviction buy" vs deterministic NEUTRAL | ✅ **Confirmed** | API `recommendation` is built from the deterministic score row, but `analysis` (LLM thesis) may contradict it. **Fixed in code**: `_execute_framework` now compares the LLM's structured `recommendation` against the deterministic score via `_reco_bucket()`; a cross-bucket conflict (e.g. LLM BUY vs deterministic NEUTRAL/SELL) sets `_validation.status = "recommendation_conflict"` with an explicit issue, so the contradiction cannot pass as `valid`. The deterministic recommendation remains authoritative. |

## Implementation Priority

```text
P0  Fundamental normalization / period alignment          (DONE)
P0  Company-scoped news filtering                        (DONE)
P0  Evidence identity + company_id scoping               (DONE)
P0  Claim validation enforcement + evidence_status       (DONE)
P0  Source-block identity + canonical resolver           (DONE)
P0  Narrative hard gate (strip unsupported claims)      (DONE)
P0  Confidence integrity (evidence-capped confidence)    (DONE)
P0  30-day high/low invariant (latest-bar floor)        (DONE)
P0  RAG resilience + embedder fallback diagnostics        (DONE)

P1  SEC filing ingestion + embedding + retrieval        (DONE)
P1  Fundamental-risk persistence parity
P1  Macro freshness metadata

P2  Metric period/method schema upgrade (value/period/method object)
P2  Output-level semantic hardening (structured provenance for
    forward-looking numbers)
```

## Cross-Field Consistency Test Invariants

The contract test suite now enforces these invariants so the original NVDA
defects cannot silently regress:

- `revenue_growth_yoy` is measured against the **year-ago quarter**, not the
  preceding quarter; omitted when no comparable period exists.
- `net_margin = net_income / revenue` and `gross_margin = gross_profit / revenue`.
- `price_change_1d_pct` and `price_change_1d` derive from the **same** provider
  fields and agree (`ratio * 100 == pct`); zero/absent change is unavailable.
- Every `source_backed_claim` resolves to registered evidence (or carries a
  canonical `source` block); unsupported claims are excluded before persistence.
- **Audit-trail preservation**: `source_backed_claims` is the *verified
  narrative* (supported claims only, via `_filter_verified_claims`), but the
  full `claim_validation` list — including `unsupported` claims and their
  `evidence_status` — is preserved verbatim in the persisted record. The
  forensic trail of what the LLM tried to say is never deleted.
- Claim validation records `evidence_status` (`available` / `unavailable` /
  `insufficient`).
- A structured LLM `recommendation` that contradicts the deterministic score
  surfaces a `recommendation_conflict` validation issue.
- News/event observations are company-scoped before reaching snapshots, RAG, or
  evidence.

## Verdict

```text
P0 fixes                         ✅ COMPLETE
Regression suite                 ✅ 166 PASS
Contract integrity               ✅ substantially complete
Evidence validation              ✅ substantially improved  (incl. audit trail)
Recommendation integrity         ✅ fixed  (deterministic authority + conflict state)
SEC financial RAG                ✅ IMPLEMENTED  (filing chunks + embedding + retrieval)
Source-block identity            ✅ FIXED  (resolve_source_block + canonical resolver)
Narrative integrity gate         ✅ FIXED  (unsupported claims stripped from output)
Confidence integrity             ✅ FIXED  (evidence-capped confidence; 0.5 ceiling with no evidence)
30-day market window invariant   ✅ FIXED  (market_window_stats floor/ceiling)
RAG resilience + diagnostics     ✅ FIXED  (keyword fallback + _rag_gap_diagnostic)
Fundamental-risk parity           ⚠️ P1
Macro freshness                   ⚠️ P1
Forward-looking semantic checks   ⚠️ P2
Metric period/method schema       ⚠️ P2

Overall DoD                       ⚠️ SUBSTANTIALLY COMPLETE  (fresh end-to-end
                                                   validation still required)
```

**P0 and the SEC filing RAG blocker are mergeable.** The system is now
structurally incapable of the specific defects found in the NVDA payload
(QoQ-mislabeled YoY, ratio/percent disagreement, contaminated news, silent
claim-validation failures, LLM overriding the deterministic recommendation).
The unsupported-claim audit trail is preserved for forensic review while
excluded from the verified narrative.

Financial claims (revenue, net income, cash flow, debt, guidance, risk
disclosures) are now auditable against the primary source through the RAG
`filings` bucket, backed by the `sec_filings` table populated from SEC XBRL.

Remaining DoD gates: fresh AAPL + second-ticker end-to-end validation
(section 10), fundamental-risk persistence parity, and macro freshness
metadata.

## Follow-up — NVDA second-ticker re-check fixes (2026-09-07)

The NVDA re-check confirmed the AAPL defect class was systemic. Four root
causes remained in code and are now fixed:

1. **Recommendation split-brain / stale risk score.** The GET handler loaded
   the company's *latest* `InvestmentScore` row, which a later
   `recalculate_scores()` run or a later analysis silently replaces. The
   recommendation block (`recommendation.score`, `reasons`, `risks`) could
   then disagree with the persisted top-level `investment_score` /
   `risk_score` (observed: 46.33 vs 68.45; "Risk score: 52" vs 48.38).
   Fix: the exact deterministic score is now persisted on the analysis row
   (`llm_analysis._score_snapshot`, written by `_fill_analysis`) and the API
   builds the recommendation block from it. The latest-row fallback remains
   only for legacy analyses persisted before the snapshot existed.

2. **Placeholder sub-scores ("Fundamental score: 50").** Sub-score
   fallbacks read only *top-level* snapshot keys while populated canonical
   snapshots can nest metrics under `metrics` / `latest_statement`, so real
   data was ignored and the 50.0 neutral placeholder was emitted. Fix:
   `_snapshot_metric()` reads both layouts (and derives net margin from the
   latest statement); `recalculate_scores()` now also passes the canonical
   fundamental snapshot instead of scoring against nothing.

3. **`entity_type_mismatch` rejections (filings).** `events` and
   `previous_analyses` buckets were already canonicalized, but the filings
   bucket was still the plural collection name (`filings`) while embeddings
   carry `entity_type="sec_filing"`, so `register_sources()` rejected every
   filing. Fix: bucket key renamed to `sec_filing` in `retrieve_context` /
   `retrieve_company_context` / pipeline empty-context, and the prompt
   citation examples updated (`sec_filing_7`). Evidence such as the NVDA
   acquisition event figure now survives attribution.

4. **LLM verdict re-injection.** `_execute_framework` sanitized the LLM's
   `recommendation` field and then re-added it from the pipeline result,
   resurrecting `analysis.recommendation: "WATCH"` alongside the
   deterministic verdict (and sometimes an empty
   `recommendation_details`). Fix: the verdict is captured before
   sanitization solely for the `recommendation_conflict` audit, and is no
   longer re-injected into the persisted payload.

`confidence_provenance` (authoritative `response_confidence` naming the
subcomponents) was verified as already rolled out and is retained.

Note: analyses persisted *before* the `_score_snapshot` fix still fall back
to the latest score row and can therefore still show drift; only fresh runs
are fully self-consistent.
