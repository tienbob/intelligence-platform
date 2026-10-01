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
    """Get investment opportunities with score breakdown + deep-analysis link.

    Screening scores (InvestmentScore) are GLOBAL market data — shared by all
    users. The deep-analysis link is USER-BOUND: only the caller's own (or
    system) completed analysis is linked, so user 2 never sees user 1's
    analysis_id from this endpoint.

    Score semantics (audit F06/F07): ``score``, ``recommendation``,
    ``components`` and ``scoring_*`` always describe the SAME screening row,
    and filtering/ordering apply to that screening score. A linked deep
    analysis is reported separately (``analysis_score`` + ``analysis_*``) and
    is never merged into the screening fields. ``sector`` is filtered in SQL
    before LIMIT so matches below the global top-N are still returned.

    NOTE: ``risk_profile`` was removed — it was accepted but never applied.
    Risk-profile filtering needs a defined band policy before it can ship.
    """
    actor = get_actor(request)
    # Latest screening score per company: max timestamp, tie-broken by highest
    # id so exactly one row per company survives. Without this the max-ts join
    # could return duplicate rows that consumed LIMIT slots and shrank the
    # page after the fact (audit F06).
    latest_score_ts = (
        select(
            InvestmentScore.company_id,
            func.max(InvestmentScore.timestamp).label("max_ts"),
        )
        .group_by(InvestmentScore.company_id)
        .subquery()
    )
    latest_score_row = (
        select(func.max(InvestmentScore.id).label("score_id"))
        .join(
            latest_score_ts,
            (InvestmentScore.company_id == latest_score_ts.c.company_id)
            & (InvestmentScore.timestamp == latest_score_ts.c.max_ts),
        )
        .group_by(InvestmentScore.company_id)
        .subquery()
    )

    query = (
        select(InvestmentScore, Company)
        .join(Company, Company.id == InvestmentScore.company_id)
        .where(InvestmentScore.id.in_(select(latest_score_row.c.score_id)))
        .where(InvestmentScore.overall_score >= min_score)
    )
    if sector:
        query = query.where(Company.sector == sector)

    result = await db.execute(
        query.order_by(desc(InvestmentScore.overall_score)).limit(limit)
    )
    rows = result.all()

    company_ids = [company.id for _, company in rows]

    # Latest completed deep analysis per company (for linking + primary score).
    # USER-BOUND: scope to own + system rows so the analysis_id link never
    # leaks another user's analysis. Bounded to the companies on this page —
    # without the IN filter the aggregate scanned the entire analyses table
    # on every request (audit P7).
    latest_analysis_by_company: dict = {}
    if company_ids:
        latest_analysis_subq = (
            select(
                Analysis.company_id,
                func.max(Analysis.created_at).label("max_ts"),
            )
            .where(Analysis.status == "completed")
            .where(Analysis.company_id.in_(company_ids))
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

    opportunities = []
    for score, company in rows:
        # Risk metric (batch-fetched above). Zero and missing are kept
        # distinct — the previous `risk_score or 50` turned a genuine 0 (or a
        # missing metric) into a fabricated mid-scale 50 (audit F07).
        risk = risk_by_company.get(company.id)

        # Screening-model component breakdown. A missing component stays null
        # (rendered as "—") instead of being coerced to 0.
        components = [
            ScoreComponent(label=label, value=getattr(score, attr, None), weight=weight)
            for label, attr, weight in _COMPONENT_WEIGHTS
        ]

        # Deep-analysis linkage — reported separately from the screening score
        # so score/recommendation/components can never disagree in the UI.
        analysis = latest_analysis_by_company.get(company.id)

        opportunities.append(
            InvestmentOpportunity(
                ticker=company.ticker,
                score=score.overall_score if score.overall_score is not None else 0,
                risk_score=risk.risk_score if risk is not None else None,
                volatility=risk.volatility if risk is not None else None,
                sector=company.sector,
                recommendation=score.recommendation or "NEUTRAL",
                # Deep-analysis linkage (own provenance, own score)
                analysis_id=analysis.analysis_id if analysis else None,
                analysis_status=analysis.status if analysis else None,
                analysis_timestamp=analysis.created_at if analysis else None,
                analysis_score=analysis.investment_score if analysis else None,
                # Screening breakdown
                components=components,
                scoring_model=score.scoring_model,
                scoring_version=score.scoring_version,
                score_timestamp=score.timestamp,
            )
        )

    return InvestmentOpportunitiesResponse(opportunities=opportunities)