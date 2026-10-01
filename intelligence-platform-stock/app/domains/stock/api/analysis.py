"""
Analysis API endpoints (Section 46).

Asynchronous analysis:
    POST /analysis/company → 202 Accepted (queued)
    GET  /analysis/{analysis_id} → status / results
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.database import get_db
from app.core.security import (
    check_idempotency,
    get_actor,
    is_admin_actor,
    owns_row,
    store_idempotency_result,
    visible_to_actor,
)
from app.domains.stock.models.analysis import Analysis, AnalysisSource
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.analysis import (
    AnalysisCreateResponse,
    AnalysisRequest,
    AnalysisResponse,
    ConfidenceBreakdown,
    InvestmentRecommendation,
)
from app.domains.stock.scoring.context_builder import ContextBuilder
from app.domains.stock.scoring.investment_scoring import InvestmentScoringEngine
from app.domains.stock.scoring.evidence import EvidenceAttributor
from app.domains.stock.scoring.llm import LLMService
from app.domains.stock.services.company_analysis import (
    AnalysisCancelled, execute_company_analysis, lock_active_analysis,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/jobs")
async def list_analysis_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List analysis jobs (lean: only fields the FE renders).

    User-bound: own rows + system (user_id IS NULL) rows. Global market
    data is intentionally NOT scoped here.
    """
    actor = get_actor(request)
    result = await db.execute(
        select(Analysis, Company.ticker)
        .options(load_only(
            Analysis.id, Analysis.analysis_id, Analysis.user_id, Analysis.status,
            Analysis.investment_score, Analysis.risk_score, Analysis.created_at,
            raiseload=True,
        ))
        .join(Company, Company.id == Analysis.company_id)
        .where(visible_to_actor(Analysis.user_id, actor))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    counts = await db.execute(
        select(Analysis.status, func.count()).where(visible_to_actor(Analysis.user_id, actor))
        .group_by(Analysis.status)
    )
    status_counts = dict(counts.all())
    from app.domains.stock.config import get_stock_config

    jobs = []
    for analysis, ticker in rows:
        jobs.append({
            "id": analysis.id,
            "analysis_id": analysis.analysis_id,
            "ticker": ticker,
            "status": analysis.status,
            "investment_score": analysis.investment_score,
            "risk_score": analysis.risk_score,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
            "can_manage": is_admin_actor(actor) or (
                analysis.user_id is not None and analysis.user_id == actor.get("user_id")
            ),
        })

    return {"jobs": jobs, "total": sum(status_counts.values()), "status_counts": status_counts,
            "supports_inclusions": get_stock_config().ANALYSIS_ENGINE != "framework"}


def _failure_reason(exc: Exception) -> str:
    """Human-readable failure reason for a dead analysis job.

    Transient provider outages (which already exhausted LLMClient's retry
    loop by the time they surface here) get a specific, actionable message
    instead of the generic one.
    """
    from app.intelligence.llm.client import classify_llm_error

    if classify_llm_error(exc) is not None:
        return (
            "The AI provider was temporarily unavailable (high demand or "
            "rate limit) and did not recover after several retries. This "
            "is usually temporary — retry the analysis in a few minutes."
        )
    return (
        "Analysis could not finish processing market data or the AI "
        "response. Retry the analysis; if it fails again, contact support "
        "with the analysis ID."
    )


async def run_company_analysis(
    analysis_id: str,
    ticker: str,
    include_news: bool,
    include_fundamentals: bool,
    include_technical: bool,
    include_macro: bool,
):
    """
    Background task for POST /analysis/company.

    Thin entry-point wrapper: all contract-producing steps live in the
    shared ``CompanyAnalysisService``. This wrapper owns only what is
    entry-point-specific — loading the pre-created row, reporting stage
    transitions to the polling frontend, and marking failures.
    """
    from app.core.database import async_session_factory
    from app.core.logging import get_logger
    from app.domains.stock.services.company_analysis import CompanyAnalysisService

    logger = get_logger(__name__)

    analysis: Analysis | None = None
    async with async_session_factory() as session:
        try:
            # Load analysis record (pre-created by the POST handler).
            analysis = await lock_active_analysis(session, analysis_id)
            analysis.status = "collecting_data"
            await session.commit()

            # Load company
            company_result = await session.execute(
                select(Company).where(Company.ticker == ticker.upper())
            )
            company = company_result.scalar_one_or_none()
            if not company:
                current = await lock_active_analysis(session, analysis_id)
                current.status = "failed"
                current.llm_analysis = {**(current.llm_analysis or {}), "_failure_reason": "The company is no longer available. Create an analysis for another ticker."}
                await session.commit()
                return

            async def _stage(name: str) -> None:
                current = await lock_active_analysis(session, analysis_id)
                current.status = name
                await session.commit()

            service = CompanyAnalysisService(
                session,
                context_builder=ContextBuilder(session),
                llm_service=LLMService(),
                evidence_attributor_factory=EvidenceAttributor,
                scoring_engine_factory=lambda s: InvestmentScoringEngine(s),
            )
            await execute_company_analysis(
                session,
                company,
                legacy_service=service,
                existing=analysis,
                include_news=include_news,
                include_fundamentals=include_fundamentals,
                include_technical=include_technical,
                include_macro=include_macro,
                on_stage=_stage,
            )

        except AnalysisCancelled:
            await session.rollback()
            logger.info("Analysis cancelled: %s", analysis_id)
        except Exception as exc:
            # Mark as failed if the analysis record exists
            logger.exception("Analysis failed: %s", exc)
            if analysis is not None:
                try:
                    await session.rollback()
                    current = await lock_active_analysis(session, analysis_id)
                    current.status = "failed"
                    current.llm_analysis = {**(current.llm_analysis or {}), "_failure_reason": _failure_reason(exc)}
                    await session.commit()
                except AnalysisCancelled:
                    await session.rollback()
                except Exception:
                    logger.exception("Could not persist analysis failure: %s", analysis_id)
                    raise



@router.post("/company", response_model=AnalysisCreateResponse, status_code=202)
async def create_company_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a company analysis job (Section 46). User-bound to the caller."""
    actor = get_actor(fastapi_request)
    from app.domains.stock.config import get_stock_config
    if get_stock_config().ANALYSIS_ENGINE == "framework" and not all((
        request.include_news, request.include_fundamentals, request.include_technical, request.include_macro
    )):
        raise HTTPException(status_code=422, detail="This analysis engine requires all data sources")

    # Company must exist before an analysis row can reference it. An untracked
    # ticker is scheduled for durable ingestion and the request answers
    # promptly: running the pipeline here would repeat the audit O02 problem
    # inside a paid-work endpoint that is already rate limited.
    from app.domains.stock.services.company_resolution import (
        get_or_schedule_missing,
        ingestion_pending,
    )

    company = await get_or_schedule_missing(request.ticker, db)
    if company is None:
        raise ingestion_pending(request.ticker)

    from app.core.jobs import reserve_job
    job = await reserve_job(db, fastapi_request, "analysis", request.model_dump(mode="json"))
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        analysis_id=analysis_id,
        company_id=company.id,
        user_id=actor.get("user_id"),
        analysis_type="company",
        analysis_version="1.0",
        status="queued",
        llm_analysis={"_request": request.model_dump()},
    )
    db.add(analysis)
    response = AnalysisCreateResponse(analysis_id=analysis_id, status="queued")
    job.response = response.model_dump(mode="json")
    await db.commit()

    return response


ACTIVE_STATUSES = {"queued", "running", "processing", "collecting_data", "calculating_metrics", "retrieving_context", "llm_analysis", "risk_analysis"}


async def _lock_owned_analysis(analysis_id: str, request: Request, db: AsyncSession):
    result = await db.execute(
        select(Analysis).where(Analysis.analysis_id == analysis_id).with_for_update()
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    actor = get_actor(request)
    if not (is_admin_actor(actor) or (
        analysis.user_id is not None and analysis.user_id == actor.get("user_id")
    )):
        raise HTTPException(status_code=404, detail="Analysis not found")

    return analysis


@router.post("/{analysis_id}/cancel")
async def cancel_analysis(analysis_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Cancel idempotently; a retry must never delete a job."""
    analysis = await _lock_owned_analysis(analysis_id, request, db)
    if analysis.status in ACTIVE_STATUSES:
        analysis.status = "cancelled"
        await db.commit()
    return {"analysis_id": analysis_id, "status": analysis.status}


@router.delete("/{analysis_id}")
async def delete_analysis(analysis_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    analysis = await _lock_owned_analysis(analysis_id, request, db)
    if analysis.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Cancel the active analysis before deleting it")
    await db.execute(delete(AnalysisSource).where(AnalysisSource.analysis_id == analysis.id))
    await db.delete(analysis)
    await db.commit()
    return {"analysis_id": analysis_id, "status": "deleted", "message": "Analysis record deleted"}


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Get analysis status and results (owner/system row, or admin/system)."""
    result = await db.execute(
        select(Analysis).where(Analysis.analysis_id == analysis_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    actor = get_actor(request)
    if not owns_row(analysis.user_id, actor):
        # Don't leak existence of another user's analysis — same 404 shape.
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Get ticker
    company_result = await db.execute(
        select(Company).where(Company.id == analysis.company_id)
    )
    company = company_result.scalar_one_or_none()

    # Only use the score captured by this run. Legacy rows have no reliable
    # score association; leave recommendation/breakdown absent for those rows.
    from types import SimpleNamespace

    snapshot = (analysis.llm_analysis or {}).get("_score_snapshot")
    score = SimpleNamespace(**snapshot) if snapshot else None

    # Get source-backed claims (Section 32)
    claims_result = await db.execute(
        select(AnalysisSource).where(AnalysisSource.analysis_id == analysis.id)
    )
    source_claims = [
        {
            "claim": c.claim,
            "source": {
                "type": c.source_type,
                "source": c.source_name,
                "metric": c.metric,
                "value": c.value,
                "period": c.period,
            },
        }
        for c in claims_result.scalars().all()
    ]

    # Build confidence breakdown (Phase B) — overall computed by Python.
    confidence_breakdown = None
    if score is not None:
        # data confidence = data_quality_score (0..1) from the score record
        data_conf = score.data_quality_score if score.data_quality_score is not None else 0.5
        # quantitative confidence = the score's own confidence (data-quality based)
        quant_conf = score.confidence if score.confidence is not None else 0.5
        # llm confidence = the LLM's self-reported confidence from the analysis payload
        llm_conf = 0.5
        if analysis.llm_analysis and isinstance(analysis.llm_analysis, dict):
            from app.domains.stock.scoring.analysis_validator import normalize_confidence, AnalysisValidationError
            try:
                llm_conf = normalize_confidence(analysis.llm_analysis.get("confidence"))
            except AnalysisValidationError:
                llm_conf = 0.5  # Historical output may predate normalization.
        # overall = Python-computed blend (e.g. geometric-ish mean of the three)
        overall = round((data_conf + quant_conf + llm_conf) / 3.0, 4)
        confidence_breakdown = ConfidenceBreakdown(
            data=round(data_conf, 4),
            quantitative=round(quant_conf, 4),
            llm=round(float(llm_conf), 4),
            overall=overall,
        )

    recommendation = None
    if score:
        recommendation = InvestmentRecommendation(
            score=score.overall_score or 0,
            confidence=score.confidence or 0,
            recommendation=score.recommendation or "HOLD",
            reasons=[
                f"Fundamental score: {score.fundamental_score:.0f}" if score.fundamental_score else "",
                f"Valuation score: {score.valuation_score:.0f}" if score.valuation_score else "",
                f"Growth score: {score.growth_score:.0f}" if score.growth_score else "",
            ],
            risks=[
                f"Risk score: {score.risk_score:.0f}" if score.risk_score else "",
            ],
            # Pass through the analysis' invalidating conditions instead
            # of always shipping an empty list.
            invalidating_conditions=list((analysis.llm_analysis or {}).get("invalidating_conditions") or []),
        )
        # Filter empty reasons
        recommendation.reasons = [r for r in recommendation.reasons if r]
        recommendation.risks = [r for r in recommendation.risks if r]

    # Debug/provenance blocks stay persisted on the row but are stripped
    # from the API response: the FE never renders them and they roughly
    # tripled the payload size (raw input context, duplicated evidence
    # packages, score snapshots, embedded request/meta copies).
    analysis_payload = {
        key: value
        for key, value in (analysis.llm_analysis or {}).items()
        if not key.startswith("_") and key not in ("evidence", "source_backed_claims")
    }

    return AnalysisResponse(
        analysis_id=analysis.analysis_id,
        status=analysis.status,
        failure_reason=(analysis.llm_analysis or {}).get("_failure_reason") if analysis.status == "failed" else None,
        request_options=(analysis.llm_analysis or {}).get("_request"),
        ticker=company.ticker if company else None,
        investment_score=analysis.investment_score,
        risk_score=analysis.risk_score,
        confidence=analysis.confidence_score,
        confidence_breakdown=confidence_breakdown,
        source_backed_claims=source_claims,
        analysis=analysis_payload,
        recommendation=recommendation,
        created_at=analysis.created_at.isoformat() if analysis.created_at else None,
        # Owner (or admin) can cancel/delete from the detail page; system rows
        # are read-only for regular users — mirrors can_manage in /analysis/jobs.
        can_manage=is_admin_actor(actor) or (
            analysis.user_id is not None and analysis.user_id == actor.get("user_id")
        ),
    )
