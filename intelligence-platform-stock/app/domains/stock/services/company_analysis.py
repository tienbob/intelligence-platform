"""
Company analysis execution core (shared contract).

ONE implementation of "run a full company analysis" — consumed by thin
entry-point wrappers:

    POST /analysis/company  →  api/analysis.py wrapper      (on_stage=…)
    Gate-3 legacy oracle    →  workers/analysis_worker.py   (on_stage=None)

The service owns every step that produces the persisted `analyses` contract
(scores, source-backed claim rows, snapshot columns, provenance). Wrappers
own only entry-point concerns: row lifecycle and progress reporting.

Canonical contract: docs/PLAN_ANALYSIS_CONTRACT.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.analysis import Analysis, AnalysisSource
from app.domains.stock.models.company import Company

logger = get_logger(__name__)

ANALYSIS_VERSION = "1.0"

StageCallback = Callable[[str], Awaitable[None]]


class AnalysisCancelled(Exception):
    """The job was cancelled or deleted while work was in progress."""


async def lock_active_analysis(session: AsyncSession, analysis_id: str) -> Analysis:
    # Serialize transitions with cancellation and refresh the identity map.
    result = await session.execute(
        select(Analysis).where(Analysis.analysis_id == analysis_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None or analysis.status == "cancelled":
        raise AnalysisCancelled(analysis_id)
    return analysis


@dataclass
class AnalysisExecutionResult:
    """Everything the execution produced; wrappers decide what to expose."""

    analysis: Analysis
    score: Any            # InvestmentScore row written by the engine
    llm_output: dict[str, Any]
    context: dict[str, Any]
    evidence_package: dict[str, Any]


def _claim_value(v: Any) -> str | None:
    """Persist the LLM-supplied claim value verbatim (DB column is String).

    Claim values are not always numeric — e.g. ``ceo_transition: "John
    Ternus"`` — so the column stores the raw value. Whole floats drop the
    cosmetic ".0" (150000000000, not "150000000000.0").
    """
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class CompanyAnalysisService:
    """Shared company-analysis orchestration (Sections 29–34, 41, 54–56).

    Dependencies are injectable so tests can substitute fakes the same way
    they do for the wrappers (monkeypatch the wrapper module's names).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        context_builder: Any,
        llm_service: Any,
        evidence_attributor_factory: Any = None,
        scoring_engine_factory: Any = None,
    ):
        self.session = session
        self.context_builder = context_builder
        self.llm_service = llm_service
        self.evidence_attributor_factory = evidence_attributor_factory
        self.scoring_engine_factory = scoring_engine_factory

    # ── Stages (each maps 1:1 to a canonical-contract concern) ──────

    async def build_context(
        self,
        company: Company,
        *,
        include_news: bool = True,
        include_fundamentals: bool = True,
        include_technical: bool = True,
        include_macro: bool = True,
    ) -> dict[str, Any]:
        return await self.context_builder.build_full_context(
            company,
            include_news=include_news,
            include_fundamentals=include_fundamentals,
            include_technical=include_technical,
            include_macro=include_macro,
        )

    def build_attributor(self, context: dict[str, Any]) -> Any | None:
        """§32: register RAG sources so the LLM stage can cite valid IDs."""
        if self.evidence_attributor_factory is None:
            return None
        attributor = self.evidence_attributor_factory()
        attributor.register_sources(context.get("rag_context", {}))
        return attributor

    async def run_llm_analysis(
        self, context: dict[str, Any], *, evidence_attributor: Any = None
    ) -> dict[str, Any]:
        return await self.llm_service.analyze_company(
            context, evidence_attributor=evidence_attributor
        )

    async def calculate_scores(self, company_id: int) -> Any:
        """Deterministic investment scoring (Section 34) — never LLM."""
        engine = (
            self.scoring_engine_factory(self.session)
            if self.scoring_engine_factory
            else None
        )
        if engine is None:
            from app.domains.stock.scoring.investment_scoring import (
                InvestmentScoringEngine,
            )

            engine = InvestmentScoringEngine(self.session)
        return await engine.calculate_score(company_id)

    # ── Persistence (single source of truth for the row contract) ───

    def _fill_analysis(
        self,
        analysis: Analysis,
        *,
        company: Company,
        context: dict[str, Any],
        llm_output: dict[str, Any],
        score: Any,
        evidence_package: dict[str, Any],
        duration_seconds: float,
    ) -> None:
        meta = llm_output.get("_meta", {})

        # Snapshots as first-class queryable columns.
        analysis.market_snapshot = context.get("market_snapshot")
        analysis.fundamental_snapshot = context.get("fundamental_snapshot")
        analysis.technical_snapshot = context.get("technical_snapshot")
        analysis.news_snapshot = context.get("news_snapshot")
        analysis.macro_snapshot = context.get("macro_snapshot")
        analysis.risk_snapshot = context.get("risk_snapshot")

        # Full LLM output plus debug embeddings of inputs/evidence.
        analysis.llm_analysis = {
            "_request": (analysis.llm_analysis or {}).get("_request") if hasattr(analysis, "llm_analysis") else None,
            **llm_output,
            "_input_context": context,
            "_evidence": evidence_package,
            "_meta_full": meta,
            "_score_snapshot": {
                field: getattr(score, field, None)
                for field in (
                    "overall_score", "risk_score", "confidence", "recommendation",
                    "fundamental_score", "valuation_score", "growth_score",
                    "data_quality_score",
                )
            },
        }

        # Deterministic scoring contract (engine-owned, never LLM opinion).
        analysis.investment_score = score.overall_score
        analysis.risk_score = score.risk_score
        analysis.confidence_score = score.confidence

        # Provenance / observability.
        analysis.analysis_version = ANALYSIS_VERSION
        analysis.prompt_version = meta.get("prompt_version")
        analysis.llm_model = meta.get("model")
        analysis.llm_tokens_used = meta.get("tokens_used")
        analysis.duration_seconds = duration_seconds

    async def persist_evidence(
        self, analysis: Analysis, llm_output: dict[str, Any]
    ) -> None:
        for claim_data in llm_output.get("source_backed_claims", []):
            source = claim_data.get("source", {})
            self.session.add(
                AnalysisSource(
                    analysis_id=analysis.id,
                    claim=claim_data.get("claim", ""),
                    source_type=source.get("type", ""),
                    source_name=source.get("source", ""),
                    metric=source.get("metric"),
                    value=_claim_value(source.get("value")),
                    period=source.get("period"),
                )
            )

    async def persist_analysis(
        self,
        *,
        company: Company,
        context: dict[str, Any],
        llm_output: dict[str, Any],
        score: Any,
        evidence_package: dict[str, Any],
        duration_seconds: float,
        existing: Analysis | None = None,
    ) -> Analysis:
        """Write the full canonical contract; create or update in place."""
        if existing is not None:
            analysis = await lock_active_analysis(self.session, existing.analysis_id)
        else:
            from uuid import uuid4

            analysis = Analysis(
                analysis_id=str(uuid4()),
                company_id=company.id,
                analysis_type="company",
            )
            self.session.add(analysis)
            # Assign the autoincrement PK NOW: child AnalysisSource rows
            # reference analysis.id explicitly, and a pre-flush id is None
            # (surfaced live as NotNullViolation on analysis_sources).
            await self.session.flush()

        self._fill_analysis(
            analysis,
            company=company,
            context=context,
            llm_output=llm_output,
            score=score,
            evidence_package=evidence_package,
            duration_seconds=duration_seconds,
        )
        analysis.status = "completed"
        await self.persist_evidence(analysis, llm_output)
        await self.session.commit()
        await self.session.refresh(analysis)
        return analysis

    # ── Orchestrator ────────────────────────────────────────────────

    async def execute(
        self,
        *,
        company: Company,
        existing: Analysis | None = None,
        include_news: bool = True,
        include_fundamentals: bool = True,
        include_technical: bool = True,
        include_macro: bool = True,
        on_stage: StageCallback | None = None,
    ) -> AnalysisExecutionResult:
        """Run the complete pipeline and persist one contract-complete row.

        ``on_stage`` is an entry-point concern: pass an awaitable to report
        progress (API wrapper commits status transitions); pass ``None``
        (worker / Gate-3 oracle) to run silently.
        """
        started = time.monotonic()

        async def stage(name: str) -> None:
            if on_stage is not None:
                await on_stage(name)

        await stage("calculating_metrics")
        context = await self.build_context(
            company,
            include_news=include_news,
            include_fundamentals=include_fundamentals,
            include_technical=include_technical,
            include_macro=include_macro,
        )

        await stage("retrieving_context")
        attributor = self.build_attributor(context)

        await stage("llm_analysis")
        llm_output = await self.run_llm_analysis(
            context, evidence_attributor=attributor
        )
        evidence_package = llm_output.get("evidence", {}) or {}

        await stage("risk_analysis")
        score = await self.calculate_scores(company.id)

        analysis = await self.persist_analysis(
            company=company,
            context=context,
            llm_output=llm_output,
            score=score,
            evidence_package=evidence_package,
            duration_seconds=round(time.monotonic() - started, 3),
            existing=existing,
        )

        logger.info(
            "Company analysis completed via shared core: ticker=%s "
            "analysis_id=%s investment_score=%s risk_score=%s",
            company.ticker,
            analysis.analysis_id,
            analysis.investment_score,
            analysis.risk_score,
        )
        return AnalysisExecutionResult(
            analysis=analysis,
            score=score,
            llm_output=llm_output,
            context=context,
            evidence_package=evidence_package,
        )


def assert_completed_analysis_contract(analysis: Any) -> None:
    """The single invariant every completed ``Analysis`` row must satisfy.

    Canonical home of the contract check (docs/PLAN_ANALYSIS_CONTRACT.md):
    tests and operational scripts import it from here so the contract, its
    owner, and its enforcement can never drift apart.
    """
    assert analysis.status == "completed"
    # Deterministic scoring columns — never null on a completed row.
    assert analysis.investment_score is not None, "investment_score missing"
    assert analysis.risk_score is not None, "risk_score missing"
    assert analysis.confidence_score is not None, "confidence_score missing"
    assert analysis.analysis_version == ANALYSIS_VERSION
    # Provenance.
    assert analysis.prompt_version
    assert analysis.llm_model
    assert analysis.llm_tokens_used is not None
    assert analysis.duration_seconds is not None
    # Snapshot columns populated (queryable relational contract).
    for col in (
        "market_snapshot", "fundamental_snapshot", "technical_snapshot",
        "news_snapshot", "macro_snapshot", "risk_snapshot",
    ):
        val = getattr(analysis, col)
        assert isinstance(val, dict), f"{col} not a dict (got {type(val)})"
    # LLM blob intact + embedded debug payloads.
    blob = analysis.llm_analysis or {}
    assert blob.get("summary"), "llm_analysis.summary missing"
    for key in ("_input_context", "_evidence", "_meta_full"):
        assert key in blob, f"llm_analysis.{key} missing"


# ── Engine selection (PLAN.md Gate 5.1) ─────────────────────────
#
# Single dispatch point: BOTH production entry points (API wrapper and
# scheduled-worker wrapper) call execute_company_analysis(); neither reads
# ANALYSIS_ENGINE itself, so a flag flip switches both simultaneously.

# Test seams — monkeypatch these to fake the framework path without LLM quota.
_framework_pipeline_factory = None  # set lazily; see _build_framework_pipeline


def _build_framework_pipeline():
    global _framework_pipeline_factory
    if _framework_pipeline_factory is None:
        from app.domains.stock.pipeline_factory import build_stock_pipeline

        _framework_pipeline_factory = build_stock_pipeline
    return _framework_pipeline_factory()


async def _load_run_score(session: AsyncSession, company_id: int, score_id: int) -> Any:
    """Load only the score identified by this pipeline run."""
    from sqlalchemy import select

    from app.domains.stock.models.analysis import InvestmentScore

    result = await session.execute(
        select(InvestmentScore)
        .where(InvestmentScore.company_id == company_id, InvestmentScore.id == score_id)
    )
    return result.scalars().first()


async def _execute_framework(
    session: AsyncSession,
    company: Company,
    *,
    existing: Analysis | None,
    on_stage: StageCallback | None,
    score_loader=None,
) -> AnalysisExecutionResult:
    """Run the generic IntelligencePipeline and persist its canonical row."""
    from app.shared.entities import AnalysisRequest, EntityRef

    async def stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name)

    await stage("calculating_metrics")
    started = time.monotonic()

    pipeline = _build_framework_pipeline()
    request = AnalysisRequest(
        entity_ref=EntityRef("stock", "company", company.ticker),
        analysis_type="company",
    )
    result = await pipeline.run(request)
    if result.status != "completed":
        raise RuntimeError(
            f"framework analysis failed for {company.ticker}: "
            f"{result.metadata.get('stages', {})}"
        )

    score_id = (result.metadata.get("scoring_metadata") or {}).get("score_id")
    if score_id is None:
        raise RuntimeError("framework analysis did not return a score identifier")
    score = await (score_loader or _load_run_score)(session, company.id, score_id)
    if score is None:
        raise RuntimeError(
            f"framework analysis produced no deterministic score row "
            f"for {company.ticker}"
        )

    meta_src = result.metadata or {}
    llm_output = {
        "summary": result.summary,
        "insights": result.insights,
        "risks": result.risks,
        "confidence": result.confidence,
        "recommendation": result.recommendation,
        "evidence": {
            "evidence_sources": [
                {
                    "source_type": e.source_type,
                    "source_name": e.source_name,
                    "metric": e.metric,
                    "value": e.value,
                    "period": e.period,
                }
                for e in result.evidence
            ],
            "source_count": len(result.evidence),
        },
        "_meta": {
            "model": meta_src.get("llm_model"),
            "provider": meta_src.get("llm_provider"),
            "prompt_name": meta_src.get("prompt_name"),
            "prompt_version": meta_src.get("prompt_version"),
            "analysis_type": meta_src.get("analysis_type"),
            "tokens_used": meta_src.get("llm_tokens"),
        },
    }

    # Persist through the SAME canonical writer so storage shape can never
    # drift between engines (PLAN.md: one persisted contract). Only the
    # persistence stage is reused; context/LLM stages belong to the pipeline.
    snapshots = meta_src.get("domain_snapshots") or {}
    service = CompanyAnalysisService(
        session, context_builder=None, llm_service=None
    )
    analysis = await service.persist_analysis(
        company=company,
        context={
            "entity": {"id": company.ticker},
            **snapshots,
        },
        llm_output=llm_output,
        score=score,
        evidence_package=llm_output["evidence"],
        duration_seconds=round(time.monotonic() - started, 3),
        existing=existing,
    )
    return AnalysisExecutionResult(
        analysis=analysis,
        score=score,
        llm_output=llm_output,
        context={},
        evidence_package=llm_output["evidence"],
    )


async def execute_company_analysis(
    session: AsyncSession,
    company: Company,
    *,
    legacy_service: CompanyAnalysisService | None = None,
    existing: Analysis | None = None,
    include_news: bool = True,
    include_fundamentals: bool = True,
    include_technical: bool = True,
    include_macro: bool = True,
    on_stage: StageCallback | None = None,
    engine: str | None = None,
    score_loader=None,
) -> AnalysisExecutionResult:
    """THE production dispatch point for company analysis.

    Reads ``ANALYSIS_ENGINE`` (default legacy) exactly once so both entry
    points always agree on the active engine (Gate 5.1).
    """
    if engine is None:
        from app.domains.stock.config import get_stock_config

        engine = get_stock_config().ANALYSIS_ENGINE

    if engine == "framework":
        if not all((include_news, include_fundamentals, include_technical, include_macro)):
            raise ValueError("Framework analysis requires all data sources")
        return await _execute_framework(
            session,
            company,
            existing=existing,
            on_stage=on_stage,
            score_loader=score_loader,
        )

    if legacy_service is None:
        raise ValueError(
            "legacy engine selected but no CompanyAnalysisService supplied"
        )
    return await legacy_service.execute(
        company=company,
        existing=existing,
        include_news=include_news,
        include_fundamentals=include_fundamentals,
        include_technical=include_technical,
        include_macro=include_macro,
        on_stage=on_stage,
    )

