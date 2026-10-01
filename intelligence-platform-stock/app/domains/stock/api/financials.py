"""
Financial data API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
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

router = APIRouter(prefix="/financials", tags=["financials"])


async def _get_company(db: AsyncSession, ticker: str) -> Company:
    """Resolve a ticker, scheduling durable ingestion when it is untracked.

    Used by statements, metrics and technical indicators, so one change here
    keeps every financial route off the ingestion path (audit O02). The lazy
    import also used to name the nonexistent `api.v1.stocks` module, which
    raised ModuleNotFoundError on every unknown ticker (audit F01).
    """
    from app.domains.stock.services.company_resolution import (
        get_or_schedule_missing,
        ingestion_pending,
    )

    company = await get_or_schedule_missing(ticker, db)
    if company is None:
        raise ingestion_pending(ticker)
    return company


@router.get("/{ticker}/statements", response_model=list[FinancialStatementResponse])
async def get_financial_statements(
    ticker: str,
    limit: int = Query(default=8, ge=1, le=40),
    db: AsyncSession = Depends(get_db),
):
    """Get financial statements for a company."""
    company = await _get_company(db, ticker)
    result = await db.execute(
        select(FinancialStatement)
        .where(FinancialStatement.company_id == company.id)
        .order_by(desc(FinancialStatement.period))
        .limit(limit)
    )
    statements = result.scalars().all()
    return [FinancialStatementResponse.model_validate(s) for s in statements]


@router.get("/{ticker}/metrics", response_model=FinancialMetricResponse)
async def get_financial_metrics(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get latest financial metrics for a company."""
    company = await _get_company(db, ticker)
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
async def get_technical_indicators(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get latest technical indicators for a company."""
    company = await _get_company(db, ticker)
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
