"""
Stock Domain Manifest — wires the stock domain into the intelligence platform.

This is the entry point discovered by the DomainRegistry.

The domain manifest adapts stock-specific providers, normalizers, context
construction, scoring, background tasks, APIs, prompts, and evidence
attribution to the domain-neutral IntelligencePlatform.

Integrity invariants
--------------------
1. The framework owns orchestration; the stock domain owns stock semantics.
2. Evidence attribution is bound to the entity being analyzed.
3. Canonical financial claims are resolved against the canonical fundamental
   snapshot belonging to the current ticker.
4. Provider/source provenance is preserved for source-backed claims.
5. Deterministic scoring remains the authoritative investment decision.
"""

from __future__ import annotations

from typing import Any, Callable


# ---------------------------------------------------------------------------
# Domain identity
# ---------------------------------------------------------------------------

DOMAIN_NAME = "stock"
DOMAIN_VERSION = "1.0"

# Version of the prompt pack under prompts/. Analysis provenance reports this
# alongside prompt_name and is intentionally independent of domain version.
PROMPT_VERSION = "1.0"


class StockDomain:
    """
    Stock & Investment Intelligence domain module.

    Implements the DomainModule protocol so the core intelligence engine can
    discover and use this domain without knowing about stocks specifically.
    """

    name = DOMAIN_NAME
    version = DOMAIN_VERSION

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    def get_providers(self) -> dict[str, Any]:
        """
        Return stock-specific data providers.

        Providers may expose the generic ``fetch(entity_ref)`` protocol for
        request-time ingestion. Worker-owned stock providers may intentionally
        expose capability-specific methods instead; the framework pipeline
        handles those as persisted/worker-fed providers.
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

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    def get_normalizers(self) -> dict[str, Any]:
        """
        Return stock-specific normalization handlers.

        Keys correspond to provider/source names used by the generic pipeline.
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

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def get_context_builder(self) -> Any:
        """
        Return the stock-specific context builder.

        The builder produces canonical stock snapshots for:

            market
            technical
            fundamental
            news
            events
            macro
            risk
        """
        from app.domains.stock.context_builder import StockContextBuilder

        return StockContextBuilder()

    # ------------------------------------------------------------------
    # Scoring strategy
    # ------------------------------------------------------------------

    def get_scoring_strategy(self) -> Any:
        """
        Return the stock-specific investment scoring strategy.

        The scoring implementation computes the deterministic investment
        decision from canonical domain data. LLM narrative must not become a
        substitute for deterministic score inputs.
        """
        from app.domains.stock.scoring import InvestmentScoringStrategy

        return InvestmentScoringStrategy()

    # ------------------------------------------------------------------
    # Intelligence tasks
    # ------------------------------------------------------------------

    def get_intelligence_tasks(self) -> list[Any]:
        """Return stock-specific background tasks for the scheduler."""
        from app.domains.stock.workers import (
            analyze_events,
            create_daily_snapshot,
            detect_anomalies,
            ingest_fundamentals,
            ingest_macro_indicators,
            ingest_rag_embeddings,
            ingest_sec_filings,
            process_news,
            recalculate_scores,
            run_scheduled_backtests,
            update_derived_metrics,
            update_market_data,
        )

        class _Task:
            """Simple wrapper satisfying the IntelligenceTask protocol."""

            def __init__(
                self,
                name: str,
                interval_minutes: int,
                fn: Callable[..., Any],
                run_immediately: bool = True,
            ):
                self.name = name
                self.interval_minutes = interval_minutes
                self._fn = fn
                self.run_immediately = run_immediately

            async def execute(self) -> None:
                result = self._fn()

                # Supports both async and sync worker functions.
                if hasattr(result, "__await__"):
                    await result

        return [
            _Task(
                "Update market data",
                5,
                update_market_data,
            ),
            _Task(
                "Process news",
                10,
                process_news,
            ),
            _Task(
                "Detect anomalies",
                15,
                detect_anomalies,
            ),
            _Task(
                "Analyze events",
                60,
                analyze_events,
            ),
            _Task(
                "Update derived metrics",
                60,
                update_derived_metrics,
            ),
            _Task(
                "Recalculate scores",
                1440,
                recalculate_scores,
            ),
            _Task(
                "Ingest fundamentals",
                1440,
                ingest_fundamentals,
            ),
            _Task(
                "Ingest SEC filings",
                1440,
                ingest_sec_filings,
            ),
            _Task(
                "Ingest macro indicators",
                1440,
                ingest_macro_indicators,
            ),
            _Task(
                "Ingest RAG embeddings",
                1440,
                ingest_rag_embeddings,
            ),
            # Point-in-time snapshot for look-ahead-free backtesting.
            #
            # run_immediately=True means a fresh environment gets its first
            # snapshot at startup instead of waiting 24h.
            _Task(
                "Create daily backtest snapshot",
                1440,
                create_daily_snapshot,
            ),
            # Drain queued backtest runs left behind by an API restart.
            _Task(
                "Run scheduled backtests",
                60,
                run_scheduled_backtests,
            ),
        ]

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def get_api_router(self):
        """Return the stock-specific FastAPI router."""
        from app.domains.stock.api import stock_router

        return stock_router

    def get_internal_router(self):
        """
        Return the internal service-to-service router.

        Used by the Rails → Python gateway and mounted by main.py through the
        DomainModule contract.
        """
        from app.domains.stock.api.internal_router import internal_router

        return internal_router

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def get_prompts(self):
        """
        Return the stock domain prompt registry.

        Prompt files are registered both under their filename stem and, for
        ``*_analysis`` prompts, under the corresponding analysis type.
        """
        from pathlib import Path

        from app.intelligence.prompts import SimplePromptRegistry

        prompts_dir = Path(__file__).parent / "prompts"
        registry = SimplePromptRegistry()

        for prompt_file in sorted(prompts_dir.glob("*.txt")):
            text = prompt_file.read_text(encoding="utf-8")

            registry.register(
                prompt_file.stem,
                text,
            )

            # Alias "company_analysis" -> "company", etc.
            if prompt_file.stem.endswith("_analysis"):
                registry.register(
                    prompt_file.stem[
                        : -len("_analysis")
                    ],
                    text,
                )

        return registry

    # ------------------------------------------------------------------
    # Evidence attribution
    # ------------------------------------------------------------------

    def get_evidence_attributor(
        self,
        context: dict[str, Any] | None = None,
    ):
        """
        Supply stock-specific claim→source attribution to the generic LLM stage.

        The framework passes the complete LLM context here. This factory binds
        the evidence resolver to:

            - the current ticker/entity,
            - optional company ID,
            - the canonical fundamental snapshot,
            - the canonical financial provider,
            - the RAG evidence registry.

        IMPORTANT:

        An LLM ``source`` block is only a reference candidate. It becomes
        supported only after StockEvidenceAttributor resolves it against the
        canonical snapshot and source provenance.
        """
        from app.domains.stock.scoring.evidence import (
            StockEvidenceAttributor,
        )

        context = context if isinstance(context, dict) else {}

        # --------------------------------------------------------------
        # Current entity
        # --------------------------------------------------------------
        entity = (
            context.get("entity")
            if isinstance(context.get("entity"), dict)
            else {}
        )

        ticker = (
            entity.get("ticker")
            or entity.get("id")
        )

        if ticker is not None:
            ticker = str(ticker).upper().strip()

        company_id = entity.get("company_id")

        # Some contexts may expose company identity under entity_id.
        if company_id is None:
            company_id = entity.get("entity_id")

        # --------------------------------------------------------------
        # Canonical fundamental snapshot
        # --------------------------------------------------------------
        fundamental = (
            context.get("fundamental_snapshot")
            if isinstance(
                context.get("fundamental_snapshot"),
                dict,
            )
            else {}
        )

        latest_statement = (
            fundamental.get("latest_statement")
            if isinstance(
                fundamental.get("latest_statement"),
                dict,
            )
            else {}
        )

        canonical_source = latest_statement.get("source")

        # --------------------------------------------------------------
        # Construct the entity-bound attributor
        # --------------------------------------------------------------
        attributor = StockEvidenceAttributor(
            fundamental_snapshot=fundamental,
            ticker=ticker,
            company_id=company_id,
            default_source_type="financial_statement",
            default_source_name=canonical_source,
        )

        # --------------------------------------------------------------
        # Register RAG evidence
        # --------------------------------------------------------------
        rag_context = (
            context.get("rag_context")
            if isinstance(
                context.get("rag_context"),
                dict,
            )
            else {}
        )

        attributor.register_sources(rag_context)

        # --------------------------------------------------------------
        # Make canonical provenance available to the attributor/diagnostics.
        # --------------------------------------------------------------
        #
        # These attributes are additive and do not change the generic
        # EvidenceAttributor contract.
        attributor.analysis_entity = {
            "ticker": ticker,
            "company_id": company_id,
            "entity_type": entity.get("entity_type"),
        }

        attributor.canonical_financial_source = canonical_source
        attributor.canonical_financial_period = latest_statement.get(
            "period"
        )

        return attributor


# ---------------------------------------------------------------------------
# Module-level instance discovered by DomainRegistry
# ---------------------------------------------------------------------------

DOMAIN = StockDomain()