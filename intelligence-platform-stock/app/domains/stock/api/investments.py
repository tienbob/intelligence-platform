"""
Investment opportunities API endpoints (Section 48).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_actor, visible_to_actor
from app.domains.stock.models.analysis import Analysis, InvestmentScore, RiskMetric
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.analysis import (
    InvestmentOpportunitiesResponse,
    InvestmentOpportunity,
    ScoreComponent,
)

router = APIRouter(prefix="/investments", tags=["investments"])

# Screening-model weights — mirrors InvestmentScoringEngine defaults so the
# breakdown bars reflect how the score was actually computed.
_COMPONENT_WEIGHTS = [
    ("Fundamentals", "fundamental_score", 0.30),
    ("Valuation", "valuation_score", 0.20),
    ("Growth", "growth_score", 0.15),
    ("Technical", "technical_score", 0.15),
    ("Sentiment", "sentiment_score", 0.10),
    ("Catalyst", "catalyst_score", 0.10),
    ("Risk", "risk_score", 0.15),
]


@router.get("/opportunities", response_model=InvestmentOpportunitiesResponse)
async def get_investment_opportunities(
    request: Request,
    risk_profile: str = Query(default="moderate"),
    min_score: float = Query(default=0, ge=0, le=100),
    sector: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get investment opportunities with score breakdown + deep-analysis link.

    Screening scores (InvestmentScore) are GLOBAL market data — shared by all
    users. The deep-analysis link is USER-BOUND: only the caller's own (or
    system) completed analysis is linked, so user 2 never sees user 1's
    analysis_id from this endpoint.
    """
    actor = get_actor(request)
    # Latest screening score per company (deduplicate).
    latest_score_subq = (
        select(
            InvestmentScore.company_id,
            func.max(InvestmentScore.timestamp).label("max_ts"),
        )
        .group_by(InvestmentScore.company_id)
        .subquery()
    )

    result = await db.execute(
        select(InvestmentScore, Company)
        .join(Company, Company.id == InvestmentScore.company_id)
        .join(
            latest_score_subq,
            (InvestmentScore.company_id == latest_score_subq.c.company_id)
            & (InvestmentScore.timestamp == latest_score_subq.c.max_ts),
        )
        .where(InvestmentScore.overall_score >= min_score)
        .order_by(desc(InvestmentScore.overall_score))
        .limit(limit)
    )
    rows = result.all()

    # Latest completed deep analysis per company (for linking + primary score).
    # USER-BOUND: scope to own + system rows so the analysis_id link never
    # leaks another user's analysis.
    latest_analysis_subq = (
        select(
            Analysis.company_id,
            func.max(Analysis.created_at).label("max_ts"),
        )
        .where(Analysis.status == "completed")
        .where(visible_to_actor(Analysis.user_id, actor))
        .group_by(Analysis.company_id)
        .subquery()
    )

    analysis_result = await db.execute(
        select(Analysis)
        .join(
            latest_analysis_subq,
            (Analysis.company_id == latest_analysis_subq.c.company_id)
            & (Analysis.created_at == latest_analysis_subq.c.max_ts),
        )
        .where(visible_to_actor(Analysis.user_id, actor))
    )
    latest_analysis_by_company = {a.company_id: a for a in analysis_result.scalars().all()}

    opportunities = []
    for score, company in rows:
        if sector and company.sector != sector:
            continue

        # Risk metric
        risk_result = await db.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company.id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = risk_result.scalar_one_or_none()

        # Build the screening-model component breakdown.
        components = []
        for label, attr, weight in _COMPONENT_WEIGHTS:
            value = getattr(score, attr, None) or 0
            components.append(ScoreComponent(label=label, value=value, weight=weight))

        # Deep-analysis linkage (prefer its score as the primary display).
        analysis = latest_analysis_by_company.get(company.id)
        if analysis:
            primary_score = (
                analysis.investment_score
                if analysis.investment_score is not None
                else (score.overall_score or 0)
            )
        else:
            primary_score = score.overall_score or 0
        primary_recommendation = score.recommendation or "NEUTRAL"

        opportunities.append(
            InvestmentOpportunity(
                ticker=company.ticker,
                score=primary_score,
                risk_score=risk.risk_score if risk and risk.risk_score else 50,
                volatility=risk.volatility if risk and risk.volatility is not None else None,
                sector=company.sector,
                recommendation=primary_recommendation,
                # Deep-analysis linkage
                analysis_id=analysis.analysis_id if analysis else None,
                analysis_status=analysis.status if analysis else None,
                analysis_timestamp=analysis.created_at if analysis else None,
                # Screening breakdown
                components=components,
                scoring_model=score.scoring_model,
                scoring_version=score.scoring_version,
                score_timestamp=score.timestamp,
            )
        )

    return InvestmentOpportunitiesResponse(opportunities=opportunities)