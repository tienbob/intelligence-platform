"""
Company analysis canonical persistence core.

ONE canonical writer for the persisted `analyses` contract (scores,
source-backed claim rows, snapshot columns, provenance). Analysis EXECUTION
belongs to the framework path:

    api/analysis.py / workers/analysis_worker.py
        → execute_company_analysis() → IntelligencePipeline → persist_analysis()

Legacy orchestration (context/LLM/scoring stages + execute()) was removed in
Gate 6 (docs/PLAN.md §6.1): the framework is the only production engine.

Canonical contract: docs/PLAN_ANALYSIS_CONTRACT.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.models.analysis import Analysis, AnalysisSource
from app.domains.stock.models.company import Company

ANALYSIS_VERSION = "1.0"

StageCallback = Any  # Callable[[str], Awaitable[None]] — kept for API compat


@dataclass
class AnalysisExecutionResult:
    """Everything the execution produced; wrappers decide what to expose."""

    analysis: Analysis
    score: Any            # InvestmentScore row written by the engine
    llm_output: dict[str, Any]
    context: dict[str, Any]
    evidence_package: dict[str, Any]


def _safe_float(v: Any) -> float | None:
    """Coerce an LLM-supplied numeric-ish value to float (DB column is Float)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


class CompanyAnalysisService:
    """Canonical persistence writer for the `analyses` contract.

    The framework path (`_execute_framework`) calls ``persist_analysis()``
    so storage shape can never drift between engines (PLAN.md: one
    persisted contract). Context/LLM/scoring stages live in the pipeline;
    this class intentionally holds NO orchestration.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

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
        analysis.market_snapshot = jsonable_encoder(context.get("market_snapshot"))
        analysis.fundamental_snapshot = jsonable_encoder(
            context.get("fundamental_snapshot")
        )
        analysis.technical_snapshot = jsonable_encoder(
            context.get("technical_snapshot")
        )
        analysis.news_snapshot = jsonable_encoder(context.get("news_snapshot"))
        analysis.macro_snapshot = jsonable_encoder(context.get("macro_snapshot"))
        analysis.risk_snapshot = jsonable_encoder(context.get("risk_snapshot"))

        # Full LLM output plus debug embeddings of inputs/evidence.
        analysis.llm_analysis = jsonable_encoder({
            **llm_output,
            "_input_context": context,
            "_evidence": evidence_package,
            "_meta_full": meta,
        })

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
                    value=_safe_float(source.get("value")),
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
            analysis = existing
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

    # ── (orchestrator removed in Gate 6 — pipeline owns execution) ──


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


# ── Engine selection (PLAN.md Gates 5.2/6) ──────────────────────
#
# Single dispatch point: BOTH production entry points (API wrapper and
# scheduled-worker wrapper) call execute_company_analysis(), which routes
# exclusively through the framework path. The legacy ANALYSIS_ENGINE flag
# and legacy orchestrator were removed after Gate 6 (rollback = git revert).

# Test seams — monkeypatch these to fake the framework path without LLM quota.
_framework_pipeline_factory = None  # set lazily; see _build_framework_pipeline


def _build_framework_pipeline():
    global _framework_pipeline_factory
    if _framework_pipeline_factory is None:
        from app.domains.stock.pipeline_factory import build_stock_pipeline

        _framework_pipeline_factory = build_stock_pipeline
    return _framework_pipeline_factory()


async def _load_latest_score(session: AsyncSession, company_id: int) -> Any:
    """Deterministic scores written by the pipeline's scoring strategy."""
    from sqlalchemy import select

    from app.domains.stock.models.analysis import InvestmentScore

    result = await session.execute(
        select(InvestmentScore)
        .where(InvestmentScore.company_id == company_id)
        .order_by(InvestmentScore.timestamp.desc())
        .limit(1)
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

    score = await (score_loader or _load_latest_score)(session, company.id)
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
        # §32: the LLM's source-backed claims drive AnalysisSource rows.
        "source_backed_claims": meta_src.get("source_backed_claims", []),
        "evidence": (
            # Prefer the LLM-attributed evidence package (RAG-cited sources
            # registered via §32); fall back to the evidence stage's
            # provider-sourced evidence.
            meta_src.get("llm_evidence")
            or {
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
            }
        ),
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
    service = CompanyAnalysisService(session)
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
    existing: Analysis | None = None,
    on_stage: StageCallback | None = None,
    score_loader=None,
) -> AnalysisExecutionResult:
    """THE production dispatch point for company analysis.

    Gate 6: Framework is the only production analysis engine.
    Both entry points (API + scheduled worker) route through here.
    """
    return await _execute_framework(
        session,
        company,
        existing=existing,
        on_stage=on_stage,
        score_loader=score_loader,
    )

