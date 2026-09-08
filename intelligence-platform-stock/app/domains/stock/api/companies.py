"""
Company API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, listing/detail show only companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.company import CompanyListResponse, CompanyResponse
from app.shared.identity import (
    requester_company_ids,
    requester_id_from_headers,
    scope_company_query,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=CompanyListResponse)
async def list_companies(
    request: Request,
    sector: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List tracked companies — scoped to the requesting user when present."""
    scope = await requester_company_ids(
        db, requester_id_from_headers(request.headers)
    )

    query = select(Company)
    if sector:
        query = query.where(Company.sector == sector)
    query = scope_company_query(query, Company, scope)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    companies = result.scalars().all()

    count_query = select(func.count(Company.id))
    if sector:
        count_query = count_query.where(Company.sector == sector)
    count_query = scope_company_query(count_query, Company, scope)
    total = (await db.execute(count_query)).scalar() or 0

    return CompanyListResponse(
        companies=[CompanyResponse.model_validate(c) for c in companies],
        total=total,
    )


@router.get("/{ticker}", response_model=CompanyResponse)
async def get_company(
    ticker: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get company details by ticker — scoped to the requesting user."""
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        # Auto-ingest only for unscoped callers; scoped users cannot summon
        # companies they were not granted.
        scope = await requester_company_ids(
            db, requester_id_from_headers(request.headers)
        )
        if scope is not None:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        from app.domains.stock.api.stocks import _auto_ingest_ticker
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
    return CompanyResponse.model_validate(company)


@router.delete("/{ticker}", status_code=204)
async def delete_company(
    ticker: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a company and all its data — scoped to the requesting user."""
    from app.domains.stock.models.alert import Alert
    from app.domains.stock.models.analysis import (
        Analysis,
        AnalysisSource,
        AnomalyScore,
        InvestmentScore,
        RiskMetric,
        TechnicalIndicator,
    )
    from app.domains.stock.models.company import Company
    from app.domains.stock.models.event import EventPriceCorrelation, MarketEvent
    from app.domains.stock.models.financial import (
        FinancialMetric,
        FinancialStatement,
        SecFiling,
    )
    from app.domains.stock.models.news import CompanyNews
    from app.domains.stock.models.stock_price import StockPrice
    from app.shared.identity import UserCompany

    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    # Scoped users can only delete companies they were granted.
    scope = await requester_company_ids(
        db, requester_id_from_headers(request.headers)
    )
    if scope is not None and company.id not in scope:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    company_id = company.id

    # Remove analysis-domain records (handle FK from analysis_sources → analyses).
    analysis_ids = (
        await db.execute(
            select(Analysis.id).where(Analysis.company_id == company_id)
        )
    ).scalars().all()

    if analysis_ids:
        await db.execute(
            delete(AnalysisSource).where(
                AnalysisSource.analysis_id.in_(analysis_ids)
            )
        )
    await db.execute(delete(Analysis).where(Analysis.company_id == company_id))
    await db.execute(
        delete(AnomalyScore).where(AnomalyScore.company_id == company_id)
    )
    await db.execute(
        delete(InvestmentScore).where(InvestmentScore.company_id == company_id)
    )
    await db.execute(
        delete(RiskMetric).where(RiskMetric.company_id == company_id)
    )
    await db.execute(
        delete(TechnicalIndicator).where(
            TechnicalIndicator.company_id == company_id
        )
    )

    # Remove event-domain records. event_price_correlations has BOTH
    # event_id and company_id FKs, so delete by company_id directly.
    await db.execute(
        delete(EventPriceCorrelation).where(
            EventPriceCorrelation.company_id == company_id
        )
    )
    await db.execute(
        delete(MarketEvent).where(MarketEvent.company_id == company_id)
    )

    # Remove financial-domain records.
    await db.execute(
        delete(FinancialStatement).where(
            FinancialStatement.company_id == company_id
        )
    )
    await db.execute(
        delete(FinancialMetric).where(FinancialMetric.company_id == company_id)
    )
    await db.execute(
        delete(SecFiling).where(SecFiling.company_id == company_id)
    )

    # Remove news associations. News rows are shared across companies via
    # the company_news join table, so only the join rows are deleted here.
    await db.execute(
        delete(CompanyNews).where(CompanyNews.company_id == company_id)
    )

    # Remove pricing data.
    await db.execute(
        delete(StockPrice).where(StockPrice.company_id == company_id)
    )

    # Remove alerts and user-company grants.
    await db.execute(delete(Alert).where(Alert.company_id == company_id))
    await db.execute(
        delete(UserCompany).where(UserCompany.company_id == company_id)
    )

    # Finally remove the company.
    await db.delete(company)
    await db.commit()
    return None
