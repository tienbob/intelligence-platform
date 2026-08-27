"""
Company API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.company import CompanyListResponse, CompanyResponse

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=CompanyListResponse)
async def list_companies(
    sector: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List all tracked companies."""
    query = select(Company)
    if sector:
        query = query.where(Company.sector == sector)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    companies = result.scalars().all()

    count_query = select(func.count(Company.id))
    if sector:
        count_query = count_query.where(Company.sector == sector)
    total = (await db.execute(count_query)).scalar() or 0

    return CompanyListResponse(
        companies=[CompanyResponse.model_validate(c) for c in companies],
        total=total,
    )


@router.get("/{ticker}", response_model=CompanyResponse)
async def get_company(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get company details by ticker."""
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        # Auto-ingest the ticker so direct navigation self-populates
        from app.domains.stock.api.v1.stocks import _auto_ingest_ticker
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
    return CompanyResponse.model_validate(company)
