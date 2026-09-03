"""
Financial data API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, financial data is only returned for companies linked to that
user via ``user_companies``. Unscoped (anonymous/system) requests see
everything (and may still auto-ingest on demand).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.analysis import TechnicalIndicator
from app.domains.stock.models.company import Company
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement
from app.domains.stock.schemas.financial import (
    FinancialMetricResponse,
    FinancialStatementResponse,
    TechnicalIndicatorResponse,
)
from app.shared.identity import company_is_scoped, requester_scope

router = APIRouter(prefix="/financials", tags=["financials"])


async def _get_company(
    db: AsyncSession, ticker: str, scope: set[int] | None
) -> Company:
    """Resolve a company, enforcing ``scope``; auto-ingest only for unscoped callers."""
    result = await db.execute(select(Company).where(Company.ticker == ticker.upper()))
    company = result.scalar_one_or_none()
    if not company or not company_is_scoped(company.id, scope):
        # Scoped users cannot summon companies they were not granted.
        if scope is not None:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        # Auto-ingest the ticker so direct navigation self-populates (unscoped).
        from app.domains.stock.api.stocks import _auto_ingest_ticker
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
    return company


@router.get("/{ticker}/statements", response_model=list[FinancialStatementResponse])
async def get_financial_statements(
    ticker: str,
    request: Request,
    limit: int = Query(default=8, le=40),
    db: AsyncSession = Depends(get_db),
):
    """Get financial statements for a company — scoped per requesting user."""
    scope = await requester_scope(request, db)
    company = await _get_company(db, ticker, scope)
    result = await db.execute(
        select(FinancialStatement)
        .where(FinancialStatement.company_id == company.id)
        .order_by(desc(FinancialStatement.period))
        .limit(limit)
    )
    statements = result.scalars().all()
    return [FinancialStatementResponse.model_validate(s) for s in statements]


@router.get("/{ticker}/metrics", response_model=FinancialMetricResponse)
async def get_financial_metrics(
    ticker: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get latest financial metrics for a company — scoped per requesting user."""
    scope = await requester_scope(request, db)
    company = await _get_company(db, ticker, scope)
    result = await db.execute(
        select(FinancialMetric)
        .where(FinancialMetric.company_id == company.id)
        .order_by(desc(FinancialMetric.timestamp))
        .limit(1)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        # Self-heal: compute metrics on-demand if they don't exist yet
        from app.domains.stock.scoring.fundamental_analysis import FundamentalAnalysisEngine
        metric = await FundamentalAnalysisEngine(db).calculate_and_store(company.id)
        if not metric:
            raise HTTPException(status_code=404, detail=f"No metrics for {ticker}")
    return FinancialMetricResponse.model_validate(metric)


@router.get("/{ticker}/technical", response_model=TechnicalIndicatorResponse)
async def get_technical_indicators(
    ticker: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get latest technical indicators for a company — scoped per requesting user."""
    scope = await requester_scope(request, db)
    company = await _get_company(db, ticker, scope)
    result = await db.execute(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.company_id == company.id)
        .order_by(desc(TechnicalIndicator.timestamp))
        .limit(1)
    )
    indicator = result.scalar_one_or_none()
    if not indicator:
        # Self-heal: compute technical indicators on-demand if they don't exist yet
        from app.domains.stock.scoring.technical_analysis import TechnicalAnalysisEngine
        indicator = await TechnicalAnalysisEngine(db).calculate_indicators(company.id)
        if not indicator:
            raise HTTPException(status_code=404, detail=f"No technical indicators for {ticker}")
    return TechnicalIndicatorResponse.model_validate(indicator)
