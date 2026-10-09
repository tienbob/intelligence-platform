# Stock framework analysis path

`ANALYSIS_ENGINE=framework` selects `execute_company_analysis` → `build_stock_pipeline` → the generic `IntelligencePipeline` for both API jobs and scheduled analysis. Default selection remains `legacy`. This change completes the framework data/context/persistence path; it does not claim the live LLM semantic sign-off or production switchover gates in PLAN.md are complete.

The Stock manifest supplies a separate analysis ingestion catalog through `get_ingestion_providers`. `PersistedStockProvider` reads the data already stored by ingestion workers, emits typed observations, and never fetches external vendors during an analysis. Unknown companies fail the ingestion stage. Vendor adapters remain available through `get_providers` for ingestion and capability discovery.

`StockSnapshotReader` owns the database queries used by both context builders. `StockContextBuilder` assembles company, market, technical, fundamental, news, event, macro, risk and anomaly snapshots into `IntelligenceContext`. It selects observations by kind and date instead of provider name, rejects observations from another company, and marks missing quantitative snapshots in metadata. The generic pipeline reports that context as degraded while allowing analysis of available data. It does not fabricate indicator values.

RAG retrieval resolves the company and uses the same company filter and query as the legacy builder. Stock's validator checks the full company-analysis schema before generic normalization. The pipeline carries the complete LLM response, evidence package, RAG input and scoring provenance to canonical persistence, including source-backed claims. LLM confidence remains distinct from deterministic score confidence. Framework progress stages map back to the API's existing lifecycle labels.

`framework_path.run_framework_analysis` is a compatibility wrapper over the same pipeline, not a second orchestration implementation.

## Verification

Unit and golden tests use persisted snapshot fixtures, recorded schema-valid LLM responses, and fake database transports. The read-only script below compares all persisted snapshots against the legacy builder for tracked companies, runs the framework with recorded LLM output, and reads existing scores. It does not spend API credits or persist analyses/scores:

```sh
docker compose exec -T python python scripts/verify_framework_context.py
```

The local database comparison passed for SPY, AAPL, NVDA, TSLA and MA. SPY correctly reported degraded context; all snapshot values matched the legacy path. A real LLM equivalence run and production flag change remain separate rollout validation steps. No database migration is required for this branch. Rebuild worker/scheduler images before activating it outside the bind-mounted Python development service.

## Analysis quality safeguards

Score components are clamped to 0–100 before weighting. Financial quality measures finite, usable profitability, valuation and growth inputs plus reporting-period freshness, rather than merely the presence of a recently computed metric row. Three usable valuation inputs are enough; P/E is optional when alternatives exist. Missing inputs and components using the neutral fallback are persisted with the run and exposed as `data_quality` on the analysis response. Score confidence follows weighted completeness, is capped at 95%, and is capped at 50% when a financial component uses fallback values. These are evidence coverage measures, not calibrated probabilities of investment success.

Recent news snapshots carry database IDs and distinct `snapshot_news_<id>` source IDs (retrieved `news_<id>` IDs refer to embeddings). Both sets are supplied to the model as evidence passages and persisted in its evidence package. Causes whose citations fail the deterministic lexical coverage check are excluded and recorded as `citation_warnings`; multiple passages may jointly support a cause. The check establishes plausible textual support, not semantic entailment or independent factual verification. The detail page shows financial coverage and excluded explanations. Historical analyses retain their original inputs and results; rerun a deep dive to apply these safeguards.
