"""Single framework execution path for API and scheduled company analyses."""
from __future__ import annotations
import time
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.stock.models.company import Company
from app.domains.stock.services.analysis_persistence import (
    AnalysisPersistence, AnalysisExecutionResult, AnalysisCancelled, Analysis,
    StageCallback, lock_active_analysis, assert_completed_analysis_contract,
)

_framework_pipeline_factory = None  # set lazily; see _build_framework_pipeline


def _build_framework_pipeline(**overrides):
    global _framework_pipeline_factory
    if _framework_pipeline_factory is None:
        from app.domains.stock.pipeline_factory import build_stock_pipeline

        _framework_pipeline_factory = build_stock_pipeline
    return _framework_pipeline_factory(**overrides)


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
    parameters=None,
) -> AnalysisExecutionResult:
    """Run the generic IntelligencePipeline and persist its canonical row."""
    from app.shared.entities import AnalysisRequest, EntityRef

    async def stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name)

    await stage("calculating_metrics")
    started = time.monotonic()

    async def pipeline_stage(name: str) -> None:
        labels = {"context": "retrieving_context", "llm": "llm_analysis", "scoring": "risk_analysis"}
        if name in labels:
            await stage(labels[name])

    pipeline = _build_framework_pipeline(stage_callback=pipeline_stage)
    request = AnalysisRequest(
        entity_ref=EntityRef("stock", "company", company.ticker),
        analysis_type="company",
        parameters=parameters or {},
    )
    result = await pipeline.run(request)
    if result.status != "completed":
        if existing is not None:
            await lock_active_analysis(session, existing.analysis_id)
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
    llm_output = dict(meta_src.get("llm_output") or {})
    if not llm_output:
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
    # Keep storage independent of pipeline stages through the canonical writer.
    snapshots = meta_src.get("domain_snapshots") or {}
    service = AnalysisPersistence(session)
    llm_output["_request"] = (getattr(existing, "llm_analysis", None) or {}).get("_request") or {
        "ticker": company.ticker, **(parameters or {}),
    }
    analysis = await service.persist_analysis(
        company=company,
        context={
            "entity": {"id": company.ticker},
            **snapshots,
            "rag_context": meta_src.get("rag_context", {}),
        },
        llm_output=llm_output,
        score=score,
        evidence_package=llm_output.get("evidence", {}),
        duration_seconds=round(time.monotonic() - started, 3),
        existing=existing,
    )
    return AnalysisExecutionResult(
        analysis=analysis,
        score=score,
        llm_output=llm_output,
        context={**snapshots, "rag_context": meta_src.get("rag_context", {})},
        evidence_package=llm_output.get("evidence", {}),
    )


async def execute_company_analysis(
    session: AsyncSession, company: Company, *, existing: Analysis | None = None,
    include_news: bool = True, include_fundamentals: bool = True,
    include_technical: bool = True, include_macro: bool = True,
    on_stage: StageCallback | None = None, engine: str | None = None, score_loader=None,
) -> AnalysisExecutionResult:
    """Both entry points execute the same framework with explicit context options."""
    if engine is None:
        from app.domains.stock.config import get_stock_config
        engine = get_stock_config().ANALYSIS_ENGINE
    if engine != "framework":
        raise ValueError("Only ANALYSIS_ENGINE=framework is supported; legacy orchestration was removed")
    return await _execute_framework(
        session, company, existing=existing, on_stage=on_stage, score_loader=score_loader,
        parameters=dict(include_news=include_news, include_fundamentals=include_fundamentals,
                        include_technical=include_technical, include_macro=include_macro),
    )
