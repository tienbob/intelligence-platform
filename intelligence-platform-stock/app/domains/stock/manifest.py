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
            MassiveProvider,
            SECProvider,
        )

        return {
            "fmp": FMPProvider(),
            "finnhub": FinnhubProvider(),
            "fred": FREDProvider(),
            "sec": SECProvider(),
            "massive": MassiveProvider(),
        }

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
                await self._fn()

        return [
            _Task("Update market data", 5, update_market_data),
            _Task("Process news", 10, process_news),
            _Task("Detect anomalies", 15, detect_anomalies),
            _Task("Analyze events", 60, analyze_events),
            _Task("Update derived metrics", 60, update_derived_metrics),
            _Task("Recalculate scores", 1440, recalculate_scores),
            _Task("Ingest fundamentals", 1440, ingest_fundamentals),
            _Task("Ingest macro indicators", 1440, ingest_macro_indicators),
            _Task("Ingest RAG embeddings", 1440, ingest_rag_embeddings),
            # Point-in-time snapshot for look-ahead-free backtesting.
            # run_immediately=True (the default) means a fresh environment
            # gets its first snapshot at startup instead of waiting 24h —
            # previously this job only lived in a hardcoded scheduler that
            # was never started, so the snapshots table stayed empty.
            _Task("Create daily backtest snapshot", 1440, create_daily_snapshot),

        ]

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

