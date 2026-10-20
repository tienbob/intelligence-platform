"""
Stock Domain Manifest — wires the stock domain into the intelligence platform.

This is the entry point discovered by the DomainRegistry.
It adapts the existing stock-specific code to the DomainModule protocol.

IMPORTANT: This file imports from the original market-intelligence codebase.
When migrating, copy the relevant modules into this domain pack and update imports.
"""

from __future__ import annotations

from typing import Any, Callable

# ── Domain identity ─────────────────────────────────────────────
DOMAIN_NAME = "stock"
DOMAIN_VERSION = "1.0"

# Version of the prompt pack under prompts/ (analysis provenance reports
# this as ``prompt_version`` alongside ``prompt_name``; see V3 §19.3).
PROMPT_VERSION = "1.0"


class StockDomain:
    """
    Stock & Investment Intelligence domain module.

    Implements the DomainModule protocol so the core intelligence engine
    can discover and use this domain without knowing about stocks specifically.
    """

    name = DOMAIN_NAME
    version = DOMAIN_VERSION

    # ── Providers ───────────────────────────────────────────────

    def get_providers(self) -> dict[str, Any]:
        """
        Return stock-specific data providers.

        Each provider fetches raw data from an external source (FMP, SEC, FRED, etc.)
        and returns it as a list of dicts.
        """
        from app.domains.stock.providers import (
            FMPProvider,
            FinnhubProvider,
            FREDProvider,
            TwelveDataProvider,
            SECProvider,
        )

        return {
            "fmp": FMPProvider(),
            "finnhub": FinnhubProvider(),
            "fred": FREDProvider(),
            "sec": SECProvider(),
            "twelve_data": TwelveDataProvider(),
        }

    def get_ingestion_providers(self) -> dict[str, Any]:
        """Analysis reads worker-persisted data; it never re-fetches vendors."""
        from app.domains.stock.providers.persisted import PersistedStockProvider
        return {"stock_database": PersistedStockProvider()}

    # ── Normalizers ─────────────────────────────────────────────

    def get_normalizers(self) -> dict[str, Any]:
        """Return stock-specific data normalizers.

        Values are the domain's normalization callables (one per data
        kind) — the same functions used by ingestion/normalization.
        """
        from app.domains.stock.normalization import (
            events,
            financials,
            news,
            prices,
        )
        from app.domains.stock.normalization.companies import (
            normalize_company_name,
            normalize_ticker,
        )

        return {
            "company_ticker": normalize_ticker,
            "company_name": normalize_company_name,
            "price": prices.normalize_price_point,
            "financial": financials.normalize_financial_statement,
            "news": news.normalize_news,
            "event": events.normalize_event,
        }

    # ── Context Builder ─────────────────────────────────────────

    def get_context_builder(self) -> Any:
        """
        Return the stock-specific context builder.

        Builds structured context for LLM analysis including:
        market snapshot, technical indicators, fundamentals, news, events, macro, risk.
        """
        from app.domains.stock.context_builder import StockContextBuilder

        return StockContextBuilder()

    # ── Scoring Strategy ────────────────────────────────────────

    def get_scoring_strategy(self) -> Any:
        """
        Return the stock-specific investment scoring strategy.

        Computes: fundamental (30%) + valuation (20%) + growth (15%) +
        technical (10%) + sentiment (10%) + catalysts (10%) - risk (15%).
        """
        from app.domains.stock.scoring import InvestmentScoringStrategy

        return InvestmentScoringStrategy()

    # ── Intelligence Tasks ──────────────────────────────────────

    def get_intelligence_tasks(self) -> list[Any]:
        """Return stock-specific background tasks for the scheduler."""
        from app.domains.stock.workers import (
            analyze_events,
            create_daily_snapshot,
            detect_anomalies,
            ingest_fundamentals,
            ingest_macro_indicators,
            ingest_rag_embeddings,
            process_news,
            recalculate_scores,
            run_scheduled_backtests,
            update_derived_metrics,
            update_market_data,
        )

        class _Task:
            """Simple wrapper to satisfy the IntelligenceTask protocol."""

            def __init__(
                self,
                name: str,
                interval_minutes: int,
                fn: Callable,
                run_immediately: bool = True,
            ):
                self.name = name
                self.interval_minutes = interval_minutes
                self._fn = fn
                self.run_immediately = run_immediately

            async def execute(self) -> None:
                from app.core.heartbeat import tracked

                await tracked(self.name, self._fn)

        # Cadences come from StockConfig (root .env) — improvement plan I3,
        # Phase 2, decision D1 = Profile A. MIN_* fields are minutes,
        # *_INTERVAL_HR fields are hours. The scheduler reads this list once
        # at boot: after changing .env, recreate the scheduler container
        # (docker compose up -d --no-deps --force-recreate scheduler) or it
        # keeps the old cadence. Tasks without a config key stay fixed and
        # are documented in MAINTENANCE.md §7.1.
        from app.domains.stock.config import get_stock_config

        cfg = get_stock_config()
        tasks = [
            _Task("Update market data", cfg.MARKET_DATA_UPDATE_INTERVAL_MIN, update_market_data),
            _Task("Process news", cfg.NEWS_PROCESSING_INTERVAL_MIN, process_news),
            _Task("Detect anomalies", cfg.ANOMALY_DETECTION_INTERVAL_MIN, detect_anomalies),
            _Task("Analyze events", cfg.EVENT_ANALYSIS_INTERVAL_HR * 60, analyze_events),
            # Fixed for now — no .env key yet (MAINTENANCE.md §7.1):
            _Task("Update derived metrics", 60, update_derived_metrics),
            _Task("Recalculate scores", cfg.SCORE_RECALCULATION_INTERVAL_HR * 60, recalculate_scores),
            _Task("Ingest fundamentals", cfg.FUNDAMENTALS_UPDATE_INTERVAL_HR * 60, ingest_fundamentals),
            _Task("Ingest macro indicators", 1440, ingest_macro_indicators),
            _Task("Ingest RAG embeddings", 1440, ingest_rag_embeddings),
            # Point-in-time snapshot for look-ahead-free backtesting.
            # run_immediately=True (the default) means a fresh environment
            # gets its first snapshot at startup instead of waiting 24h —
            # previously this job only lived in a hardcoded scheduler that
            # was never started, so the snapshots table stayed empty.
            _Task("Create daily backtest snapshot", 1440, create_daily_snapshot),
        ]

        # Fail loudly on misconfiguration: the scheduler's per-domain error
        # handling would otherwise silently register zero jobs.
        invalid = [t.name for t in tasks if t.interval_minutes <= 0]
        if invalid:
            raise ValueError(
                "Non-positive scheduler interval(s) configured for: "
                + ", ".join(invalid)
            )
        return tasks

    # ── API Router ──────────────────────────────────────────────

    def get_api_router(self):
        """Return the stock-specific FastAPI router."""
        from app.domains.stock.api import stock_router

        return stock_router

    def get_internal_router(self):
        """
        Return the internal service-to-service router (Rails→Python gateway).

        Reuses the domain's endpoint routers but authenticates via the
        internal service key instead of user JWTs. Mounted at /internal by
        main.py through the DomainModule contract.
        """
        from app.domains.stock.api.internal_router import internal_router

        return internal_router

    # ── Prompts ─────────────────────────────────────────────────

    def get_prompts(self) -> PromptRegistry:
        """Return the stock domain's prompt registry."""
        from pathlib import Path

        from app.intelligence.prompts import SimplePromptRegistry

        prompts_dir = Path(__file__).parent / "prompts"
        registry = SimplePromptRegistry()
        for prompt_file in prompts_dir.glob("*.txt"):
            text = prompt_file.read_text()
            registry.register(prompt_file.stem, text)
            # Alias by analysis type ("company_analysis" → "company") so
            # the domain-neutral pipeline can request prompts by
            # ``AnalysisRequest.analysis_type`` without knowing file names.
            if prompt_file.stem.endswith("_analysis"):
                registry.register(prompt_file.stem[: -len("_analysis")], text)
        return registry

    # ── Evidence attribution (optional, §32) ─────────────────────

    @staticmethod
    def excluded_sections(parameters):
        sections = {"include_news": ("news_snapshot", "event_snapshot"),
                    "include_fundamentals": ("fundamental_snapshot",),
                    "include_technical": ("technical_snapshot", "anomaly_snapshot"),
                    "include_macro": ("macro_snapshot",)}
        return {section for flag, names in sections.items() if not parameters.get(flag, True) for section in names}

    def filter_analysis_context(self, context, parameters):
        excluded = self.excluded_sections(parameters)
        context.domain_snapshots = {k: v for k, v in context.domain_snapshots.items() if k not in excluded}
        context.observations = [o for o in context.observations if o.kind not in excluded]
        context.metadata["missing_snapshots"] = [k for k in context.metadata.get("missing_snapshots", []) if k not in excluded]
        context.metadata["excluded_snapshots"] = sorted(excluded)
        return context

    @staticmethod
    def filter_rag_context(rag, parameters):
        excluded = set()
        if not parameters.get("include_news", True):
            excluded.update(("news", "events"))
        if not parameters.get("include_fundamentals", True):
            excluded.add("filings")
        return {k: v for k, v in rag.items() if k not in excluded}

    def get_llm_context(self, context):
        """Snapshots already contain the persisted observation/evidence values."""
        return {key: value for key, value in context.items() if key not in ("observations", "evidence")}

    def get_evidence_attributor(self, context):
        """Supply claim→source attribution to the generic LLM stage.

        The framework pipeline calls this (when present) and passes the
        result to the LLM service as ``evidence_attributor``, so analyses
        running through the generic pipeline keep source-attributed claims
        exactly like ``framework_path.analyze_llm`` and the legacy worker.
        ``context`` is the dict the pipeline builds for the LLM (contains
        ``rag_context``).
        """
        from app.domains.stock.scoring.evidence import EvidenceAttributor

        attributor = EvidenceAttributor()
        rag = context.get("rag_context", {}) if isinstance(context, dict) else {}
        attributor.register_sources(rag)
        return attributor


# ── Module-level instance (discovered by registry) ──────────────
DOMAIN = StockDomain()

