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
    min_score: float = Query(default=0, ge=0, le=100),
    sector: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Rank by the latest visible completed deep dive, falling back to screening.

    Visibility is applied before selecting each company's latest analysis.
    Score filtering and LIMIT use the same effective score shown in the UI.
    """
    actor = get_actor(request)
    score_ranked = select(
        InvestmentScore.id.label("id"),
        func.row_number().over(partition_by=InvestmentScore.company_id,
                               order_by=(InvestmentScore.timestamp.desc(), InvestmentScore.id.desc())).label("rank"),
    ).subquery()
    analysis_ranked = select(
        Analysis.id.label("id"),
        func.row_number().over(partition_by=Analysis.company_id,
                               order_by=(Analysis.created_at.desc(), Analysis.id.desc())).label("rank"),
    ).where(Analysis.status == "completed").where(visible_to_actor(Analysis.user_id, actor)).subquery()
    effective_score = func.coalesce(Analysis.investment_score, InvestmentScore.overall_score)
    query = (
        select(InvestmentScore, Company, Analysis)
        .select_from(Company)
        .outerjoin(InvestmentScore, (InvestmentScore.company_id == Company.id)
                   & InvestmentScore.id.in_(select(score_ranked.c.id).where(score_ranked.c.rank == 1)))
        .outerjoin(Analysis, (Analysis.company_id == Company.id)
                   & Analysis.id.in_(select(analysis_ranked.c.id).where(analysis_ranked.c.rank == 1)))
        .where(effective_score >= min_score)
    )
    if sector:
        query = query.where(Company.sector == sector)
    result = await db.execute(query.order_by(effective_score.desc(), Company.id).limit(limit))
    rows = result.all()
    company_ids = [company.id for _, company, _ in rows]

    # Batch-fetch the latest risk metric per company (one query instead of
    # one query per company in the loop below).
    risk_by_company: dict = {}
    if company_ids:
        latest_risk_subq = (
            select(
                RiskMetric.company_id,
                func.max(RiskMetric.timestamp).label("max_ts"),
            )
            .where(RiskMetric.company_id.in_(company_ids))
            .group_by(RiskMetric.company_id)
            .subquery()
        )
        risk_result = await db.execute(
            select(RiskMetric)
            .join(
                latest_risk_subq,
                (RiskMetric.company_id == latest_risk_subq.c.company_id)
                & (RiskMetric.timestamp == latest_risk_subq.c.max_ts),
            )
            .where(RiskMetric.company_id.in_(company_ids))
        )
        for rm in risk_result.scalars().all():
            # setdefault: first row wins on timestamp ties.
            risk_by_company.setdefault(rm.company_id, rm)

    opportunities = [
        _opportunity_from_rows(score, company, analysis, risk_by_company.get(company.id))
        for score, company, analysis in rows
    ]
    return InvestmentOpportunitiesResponse(opportunities=opportunities)


def _opportunity_from_rows(score, company, analysis, risk):
    """Keep the displayed fields tied to one score source, including genuine zero."""
    use_analysis = analysis is not None and analysis.investment_score is not None
    snapshot = (analysis.llm_analysis or {}).get("_score_snapshot") or {} if use_analysis else {}
    def component(attr):
        return snapshot.get(attr) if use_analysis else getattr(score, attr, None)
    return InvestmentOpportunity(
        ticker=company.ticker,
        score=analysis.investment_score if use_analysis else score.overall_score,
        score_source="analysis" if use_analysis else "screening",
        screening_score=score.overall_score if score is not None else None,
        risk_score=analysis.risk_score if use_analysis else risk.risk_score if risk is not None else None,
        volatility=(analysis.risk_snapshot or {}).get("volatility") if use_analysis else risk.volatility if risk is not None else None,
        sector=company.sector,
        recommendation=(snapshot.get("recommendation") or "NEUTRAL") if use_analysis else score.recommendation or "NEUTRAL",
        analysis_id=analysis.analysis_id if analysis else None,
        analysis_status=analysis.status if analysis else None,
        analysis_timestamp=analysis.created_at if analysis else None,
        analysis_score=analysis.investment_score if analysis else None,
        components=[ScoreComponent(label=label, value=component(attr), weight=weight)
                    for label, attr, weight in _COMPONENT_WEIGHTS],
        scoring_model=snapshot.get("scoring_model") if use_analysis else score.scoring_model,
        scoring_version=snapshot.get("scoring_version") if use_analysis else score.scoring_version,
        score_timestamp=analysis.created_at if use_analysis else score.timestamp,
    )
