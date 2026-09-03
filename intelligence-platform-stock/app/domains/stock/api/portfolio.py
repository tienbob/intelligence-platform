"""
Portfolio optimizer API endpoint.

Keeps only the stateless optimizer, which is intended for future use. The
portfolio-management CRUD (holdings, snapshots, history, performance,
rebalance, drift, backtest) has been removed — it is no longer surfaced by the
frontend, which is now an AI research/opportunities workspace.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.analysis import InvestmentScore, RiskMetric
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.portfolio import (
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
)
from app.domains.stock.scoring.portfolio_optimizer import PortfolioOptimizer
from app.shared.identity import requester_scope, scoped_where

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _build_opportunities(
    db: AsyncSession,
    scope: set[int] | None,
    tickers: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Load latest investment scores with risk data, deduplicated per company.

    ``scope`` is the requesting user's granted company-id set (``None`` → all).
    """
    latest_score_subq = (
        select(
            InvestmentScore.company_id,
            func.max(InvestmentScore.timestamp).label("max_ts"),
        )
        .group_by(InvestmentScore.company_id)
        .subquery()
    )

    query = (
        select(InvestmentScore, Company)
        .join(Company, Company.id == InvestmentScore.company_id)
        .join(
            latest_score_subq,
            (InvestmentScore.company_id == latest_score_subq.c.company_id)
            & (InvestmentScore.timestamp == latest_score_subq.c.max_ts),
        )
        .order_by(desc(InvestmentScore.overall_score))
        .limit(limit)
    )

    query = scoped_where(query, InvestmentScore.company_id, scope)

    if tickers:
        query = query.where(Company.ticker.in_([t.upper() for t in tickers]))

    result = await db.execute(query)
    rows = result.all()

    opportunities: list[dict[str, Any]] = []
    for score, company in rows:
        risk_result = await db.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company.id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = risk_result.scalar_one_or_none()

        opportunities.append({
            "ticker": company.ticker,
            "score": score.overall_score if score and score.overall_score else 50,
            "risk_score": risk.risk_score if risk and risk.risk_score else 50,
            "volatility": risk.volatility if risk and risk.volatility else 0.25,
            "sector": company.sector or "Unknown",
        })

    return opportunities


@router.post("/optimize", response_model=PortfolioOptimizeResponse)
async def optimize_portfolio(
    request: PortfolioOptimizeRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Optimize portfolio allocation (stateless; kept for future use) — scoped
    to the requesting user's companies.
    """
    scope = await requester_scope(fastapi_request, db)
    opportunities = await _build_opportunities(
        db, scope, tickers=request.tickers
    )
    return PortfolioOptimizer().optimize(opportunities, request)