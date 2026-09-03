"""
Investment opportunities API endpoints (Section 48).

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, opportunities are only shown for companies linked to that user
via ``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.analysis import InvestmentScore, RiskMetric
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.analysis import (
    InvestmentOpportunitiesResponse,
    InvestmentOpportunity,
)
from app.shared.identity import requester_scope, scoped_where

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/opportunities", response_model=InvestmentOpportunitiesResponse)
async def get_investment_opportunities(
    request: Request,
    risk_profile: str = Query(default="moderate"),
    min_score: float = Query(default=0, ge=0, le=100),
    sector: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get investment opportunities (Section 48) — scoped per requesting user."""
    # Get the latest investment score per company (deduplicate).
    # A company may have multiple score records from repeated analysis runs;
    # we only want the most recent one.
    from sqlalchemy import func

    scope = await requester_scope(request, db)

    latest_score_subq = (
        select(
            InvestmentScore.company_id,
            func.max(InvestmentScore.timestamp).label("max_ts"),
        )
        .group_by(InvestmentScore.company_id)
        .subquery()
    )

    result = await db.execute(
        scoped_where(
            select(InvestmentScore, Company)
            .join(Company, Company.id == InvestmentScore.company_id)
            .join(
                latest_score_subq,
                (InvestmentScore.company_id == latest_score_subq.c.company_id)
                & (InvestmentScore.timestamp == latest_score_subq.c.max_ts),
            )
            .where(InvestmentScore.overall_score >= min_score)
            .order_by(desc(InvestmentScore.overall_score))
            .limit(limit),
            InvestmentScore.company_id,
            scope,
        )
    )
    rows = result.all()

    opportunities = []
    for score, company in rows:
        if sector and company.sector != sector:
            continue

        # Get risk score
        risk_result = await db.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company.id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = risk_result.scalar_one_or_none()

        # Recommended weight based on score and risk
        risk_score = risk.risk_score if risk and risk.risk_score else 50
        recommended_weight = max(0.02, min(0.15, (score.overall_score or 0) / 100 * 0.15 * (1 - risk_score / 200)))

        opportunities.append(
            InvestmentOpportunity(
                ticker=company.ticker,
                score=score.overall_score or 0,
                risk_score=risk_score,
                volatility=risk.volatility if risk and risk.volatility is not None else None,
                sector=company.sector,
                confidence=score.confidence or 0,
                recommendation=score.recommendation or "NEUTRAL",
                reason=f"Score {score.overall_score:.0f}/100, recommendation: {score.recommendation}",
                recommended_weight=round(recommended_weight, 4),
            )
        )

    return InvestmentOpportunitiesResponse(opportunities=opportunities)