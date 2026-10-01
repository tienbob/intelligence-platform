"""
Portfolio optimizer API endpoint.

Keeps only the stateless optimizer, which is intended for future use. The
portfolio-management CRUD (holdings, snapshots, history, performance,
rebalance, drift, backtest) has been removed — it is no longer surfaced by the
frontend, which is now an AI research/opportunities workspace.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.analysis import InvestmentScore
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.portfolio import (
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
)
from app.domains.stock.scoring.risk import RiskEngine

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _build_opportunities(
    db: AsyncSession,
    tickers: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Load latest investment scores with risk data, deduplicated per company."""
    latest_score_subq = (
        select(InvestmentScore.id)
        .distinct(InvestmentScore.company_id)
        .order_by(InvestmentScore.company_id, InvestmentScore.timestamp.desc(), InvestmentScore.id.desc())
        .subquery()
    )

    query = (
        select(InvestmentScore, Company)
        .join(Company, Company.id == InvestmentScore.company_id)
        .join(latest_score_subq, InvestmentScore.id == latest_score_subq.c.id)
        .order_by(desc(InvestmentScore.overall_score), Company.id)
        .limit(limit)
    )

    if tickers:
        query = query.where(Company.ticker.in_([t.upper() for t in tickers]))

    result = await db.execute(query)
    rows = result.all()

    risks = await RiskEngine(db).get_latest_risks([company.id for _, company in rows])
    opportunities: list[dict[str, Any]] = []
    for score, company in rows:
        risk = risks.get(company.id)

        opportunities.append({
            "ticker": company.ticker,
            "score": score.overall_score if score and score.overall_score is not None else 50,
            "risk_score": risk.risk_score if risk and risk.risk_score is not None else 50,
            "volatility": risk.volatility if risk and risk.volatility is not None else 0.25,
            "sector": company.sector or "Unknown",
        })

    return opportunities


@router.post("/optimize", response_model=PortfolioOptimizeResponse)
async def optimize_portfolio(
    request: PortfolioOptimizeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Optimize portfolio allocation (stateless; kept for future use).
    """
    from app.domains.stock.scoring.portfolio_optimizer import PortfolioOptimizer

    opportunities = await _build_opportunities(db, tickers=request.tickers)
    return PortfolioOptimizer().optimize(opportunities, request)