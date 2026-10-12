# Stock framework analysis path

`ANALYSIS_ENGINE=framework` selects `execute_company_analysis` → `build_stock_pipeline` → the generic `IntelligencePipeline` for both API jobs and scheduled analysis. Framework is the only supported engine; the legacy orchestration has been removed. This change completes the framework data/context/persistence path; it does not claim the live LLM semantic sign-off or production switchover gates in PLAN.md are complete.

Disabled news and fundamentals also skip their RAG searches and embedding requests. Previous-analysis retrieval remains enabled. `scripts/gate3_equivalence.py` now checks live framework health; historical legacy scores are informational because current market data and scoring rules can change. It exits with a nonzero status when a runtime check fails. Equivalence requires frozen inputs and is not established by this live check.

The Stock manifest supplies a separate analysis ingestion catalog through `get_ingestion_providers`. `PersistedStockProvider` reads the data already stored by ingestion workers, emits typed observations, and never fetches external vendors during an analysis. Unknown companies fail the ingestion stage. Vendor adapters remain available through `get_providers` for ingestion and capability discovery.

`StockSnapshotReader` owns the persisted snapshot queries. `StockContextBuilder` assembles company, market, technical, fundamental, news, event, macro, risk and anomaly snapshots into `IntelligenceContext`. It selects observations by kind and date instead of provider name, rejects observations from another company, and marks missing quantitative snapshots in metadata. The generic pipeline reports that context as degraded while allowing analysis of available data. It does not fabricate indicator values.

RAG retrieval resolves the company and uses the same company filter and query as the legacy builder. Stock's validator checks the full company-analysis schema before generic normalization. The pipeline carries the complete LLM response, evidence package, RAG input and scoring provenance to canonical persistence, including source-backed claims. LLM confidence remains distinct from deterministic score confidence. Framework progress stages map back to the API's existing lifecycle labels.

`framework_path.run_framework_analysis` is a compatibility wrapper over the same pipeline, not a second orchestration implementation.

## Verification

Unit and golden tests use persisted snapshot fixtures, recorded schema-valid LLM responses, and fake database transports. The read-only script below compares all persisted snapshots against the shared snapshot reader for tracked companies, runs the framework with recorded LLM output, and reads existing scores. It does not spend API credits or persist analyses/scores:

```sh
docker compose exec -T python python scripts/verify_framework_context.py
```

The local database comparison passed for SPY, AAPL, NVDA, TSLA and MA. SPY correctly reported degraded context; all snapshot values matched the shared reader. A real LLM equivalence run and production flag change remain separate rollout validation steps. Migration 0022 adds concurrent indexes for the Opportunities latest-row lookups. Apply it before deploying the updated query. Rebuild worker/scheduler images before activating it outside the bind-mounted Python development service.

## Analysis quality safeguards

Score components are clamped to 0–100 before weighting. Financial quality measures finite, usable profitability, valuation and growth inputs plus reporting-period freshness, rather than merely the presence of a recently computed metric row. Three usable valuation inputs are enough; P/E is optional when alternatives exist. Missing inputs and components using the neutral fallback are persisted with the run and exposed as `data_quality` on the analysis response. Score confidence follows weighted completeness, is capped at 95%, and is capped at 50% when a financial component uses fallback values. These are evidence coverage measures, not calibrated probabilities of investment success.

Recent news snapshots carry database IDs and distinct `snapshot_news_<id>` source IDs (retrieved `news_<id>` IDs refer to embeddings). Both sets are supplied to the model as evidence passages and persisted in its evidence package. Causes whose citations fail the deterministic lexical coverage check are excluded and recorded as `citation_warnings`; multiple passages may jointly support a cause. The check establishes plausible textual support, not semantic entailment or independent factual verification. The detail page shows financial coverage and excluded explanations. Historical analyses retain their original inputs and results; rerun a deep dive to apply these safeguards.

Stock projects snapshots into the LLM context once; observation and evidence copies remain available to pipeline stages but are omitted from the Stock prompt. Retrieved and recent-news passages are sent once with source-ID references in their original buckets. Original inputs remain intact for persistence. The framework reports company prompt version 1.1. Financial dictionaries containing only metadata or null/non-finite values mark context construction as degraded; zero is a valid financial value.

Opportunities uses correlated lateral lookups with `LIMIT 1` and timestamp/ID tie-breaking for each company. Analysis visibility is applied inside that lookup before selecting the latest row. Migration 0022 adds ordered indexes, including a partial index for completed analyses. The final effective scores still determine ordering, filtering and the page limit.

## Legacy orchestration removal

Both API jobs and scheduled analysis call `execute_company_analysis`, which always runs the framework. `AnalysisPersistence` owns result writing, evidence rows, locking and cancellation checks; it does not orchestrate an analysis. The legacy `CompanyAnalysisService.execute` and `scoring/context_builder.py` are removed. Scoring engines, snapshot readers, the API job wrapper and scheduled worker remain. Change any deployment still using `ANALYSIS_ENGINE=legacy` to `framework` before rebuilding Python, worker and scheduler images. This is a code switchover, not a claim that production monitoring or storage-ownership gates have been signed off.

Request inclusion flags travel in framework request parameters. The persisted provider skips disabled snapshot queries, the domain excludes their prompt sections, and news/filing RAG buckets are filtered accordingly. Disabled sections do not mark context as missing; enabled sections with unavailable data still do. Deterministic scoring continues to use its stored market inputs independently of narrative inclusion flags, matching the previous scoring behavior. Persisted request options identify exclusions; omitted relational snapshots are empty dictionaries.
