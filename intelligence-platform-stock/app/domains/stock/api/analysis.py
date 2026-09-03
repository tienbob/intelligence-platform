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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import check_idempotency, store_idempotency_result
from app.domains.stock.models.analysis import Analysis, AnalysisSource, InvestmentScore
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.analysis import (
    AnalysisCreateResponse,
    AnalysisRequest,
    AnalysisResponse,
    ConfidenceBreakdown,
    InvestmentRecommendation,
)
from app.domains.stock.services.company_analysis import execute_company_analysis
from app.shared.identity import (
    company_is_scoped,
    requester_scope,
    scoped_where,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/jobs")
async def list_analysis_jobs(
    request: Request,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List analysis jobs with status — scoped to the requesting user's companies."""
    from sqlalchemy import func

    scope = await requester_scope(request, db)

    query = (
        select(Analysis, Company.ticker)
        .join(Company, Company.id == Analysis.company_id)
    )
    query = scoped_where(query, Analysis.company_id, scope)
    query = query.order_by(Analysis.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    count_query = select(func.count(Analysis.id))
    count_query = scoped_where(count_query, Analysis.company_id, scope)
    total = (await db.execute(count_query)).scalar() or 0

    jobs = []
    for analysis, ticker in rows:
        jobs.append({
            "id": analysis.id,
            "analysis_id": analysis.analysis_id,
            "ticker": ticker,
            "status": analysis.status,
            "investment_score": analysis.investment_score,
            "risk_score": analysis.risk_score,
            "confidence_score": analysis.confidence_score,
            "llm_model": analysis.llm_model,
            "llm_tokens_used": analysis.llm_tokens_used,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        })

    return {"jobs": jobs, "total": total}


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

    Gate 6: Analysis execution delegated to the framework path via
    execute_company_analysis(). This wrapper owns only API-specific
    concerns — loading the pre-created row, reporting stage transitions
    to the polling frontend, and marking failures.
    """
    from app.core.database import async_session_factory
    from app.core.logging import get_logger

    logger = get_logger(__name__)

    analysis: Analysis | None = None
    async with async_session_factory() as session:
        try:
            # Load analysis record (pre-created by the POST handler).
            result = await session.execute(
                select(Analysis).where(Analysis.analysis_id == analysis_id)
            )
            analysis = result.scalar_one()
            analysis.status = "collecting_data"
            await session.commit()

            # Load company
            company_result = await session.execute(
                select(Company).where(Company.ticker == ticker.upper())
            )
            company = company_result.scalar_one_or_none()
            if not company:
                analysis.status = "failed"
                await session.commit()
                return

            async def _stage(name: str) -> None:
                assert analysis is not None
                analysis.status = name
                await session.commit()

            await execute_company_analysis(
                session,
                company,
                existing=analysis,
                on_stage=_stage,
            )

        except Exception as exc:
            # Mark as failed if the analysis record exists
            logger.exception("Analysis failed: %s", exc)
            if analysis is not None:
                try:
                    analysis.status = "failed"
                    await session.commit()
                except Exception:
                    pass



@router.post("/company", response_model=AnalysisCreateResponse, status_code=202)
async def create_company_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    fastapi_request: Request = None,
):
    """Create a company analysis job (Section 46) — scoped per requesting user."""
    # Idempotency check (Architecture §101)
    idempotency_key = await check_idempotency(fastapi_request)

    scope = await requester_scope(fastapi_request, db)

    # Verify company exists — auto-ingest only for unscoped callers
    result = await db.execute(
        select(Company).where(Company.ticker == request.ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        if scope is not None:
            # Scoped users cannot summon companies they were not granted.
            raise HTTPException(status_code=404, detail=f"Company {request.ticker} not found")
        from app.domains.stock.api.stocks import _auto_ingest_ticker
        company = await _auto_ingest_ticker(request.ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {request.ticker} not found")

    if not company_is_scoped(company.id, scope):
        raise HTTPException(status_code=404, detail=f"Company {request.ticker} not found")

    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        analysis_id=analysis_id,
        company_id=company.id,
        analysis_type="company",
        analysis_version="1.0",
        status="queued",
    )
    db.add(analysis)
    await db.commit()

    # Schedule background task
    background_tasks.add_task(
        run_company_analysis,
        analysis_id,
        request.ticker.upper(),
        request.include_news,
        request.include_fundamentals,
        request.include_technical,
        request.include_macro,
    )

    response = AnalysisCreateResponse(analysis_id=analysis_id, status="queued")

    # Store idempotency result
    if idempotency_key:
        store_idempotency_result(idempotency_key, 202, response.model_dump())

    return response


@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cancel or delete an analysis job — scoped to the requesting user."""
    result = await db.execute(
        select(Analysis).where(Analysis.analysis_id == analysis_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    scope = await requester_scope(request, db)
    if not company_is_scoped(analysis.company_id, scope):
        raise HTTPException(status_code=404, detail="Analysis not found")

    active_statuses = {"queued", "collecting_data", "calculating_metrics", "retrieving_context", "llm_analysis", "risk_analysis"}
    if analysis.status in active_statuses:
        analysis.status = "cancelled"
        await db.commit()
        return {"analysis_id": analysis_id, "status": "cancelled", "message": "Analysis job cancelled"}

    # Already completed, failed, or cancelled — delete the record
    await db.delete(analysis)
    await db.commit()
    return {"analysis_id": analysis_id, "status": "deleted", "message": "Analysis record deleted"}


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get analysis status and results (Section 46) — scoped per requesting user."""
    result = await db.execute(
        select(Analysis).where(Analysis.analysis_id == analysis_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    scope = await requester_scope(request, db)
    if not company_is_scoped(analysis.company_id, scope):
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Get ticker
    company_result = await db.execute(
        select(Company).where(Company.id == analysis.company_id)
    )
    company = company_result.scalar_one_or_none()

    # Get latest investment score for recommendation
    score_result = await db.execute(
        select(InvestmentScore)
        .where(InvestmentScore.company_id == analysis.company_id)
        .order_by(InvestmentScore.timestamp.desc())
        .limit(1)
    )
    score = score_result.scalar_one_or_none()

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
            llm_conf = analysis.llm_analysis.get("confidence", 0.5)
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
            invalidating_conditions=[],
        )
        # Filter empty reasons
        recommendation.reasons = [r for r in recommendation.reasons if r]
        recommendation.risks = [r for r in recommendation.risks if r]

    return AnalysisResponse(
        analysis_id=analysis.analysis_id,
        status=analysis.status,
        ticker=company.ticker if company else None,
        investment_score=analysis.investment_score,
        risk_score=analysis.risk_score,
        confidence=analysis.confidence_score,
        confidence_breakdown=confidence_breakdown,
        source_backed_claims=source_claims,
        analysis=analysis.llm_analysis,
        recommendation=recommendation,
        created_at=analysis.created_at.isoformat() if analysis.created_at else None,
    )
