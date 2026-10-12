"""Canonical Stock analysis persistence and cancellation contract."""
from __future__ import annotations

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


class AnalysisPersistence:
    """Canonical result writer shared by all framework entry points."""

    def __init__(self, session: AsyncSession):
        self.session = session

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
        analysis.market_snapshot = context.get("market_snapshot", {})
        analysis.fundamental_snapshot = context.get("fundamental_snapshot", {})
        analysis.technical_snapshot = context.get("technical_snapshot", {})
        analysis.news_snapshot = context.get("news_snapshot", {})
        analysis.macro_snapshot = context.get("macro_snapshot", {})
        analysis.risk_snapshot = context.get("risk_snapshot", {})

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
                    "data_quality_score", "technical_score", "sentiment_score",
                    "catalyst_score", "scoring_model", "scoring_version", "validation_issues",
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


