"""
Company API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.company import CompanyListResponse, CompanyResponse

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=CompanyListResponse)
async def list_companies(
    q: str | None = Query(default=None, max_length=100),
    sector: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all tracked companies (lean rows: what the FE table renders)."""
    query = select(Company)
    if sector:
        query = query.where(Company.sector == sector)
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(or_(Company.ticker.ilike(f"%{term}%", escape="\\"), Company.name.ilike(f"%{term}%", escape="\\")))
    query = query.order_by(Company.ticker, Company.id).offset(offset).limit(limit)

    result = await db.execute(query)
    companies = result.scalars().all()

    return CompanyListResponse(
        companies=[CompanyResponse.model_validate(c) for c in companies],
    )


@router.get("/{ticker}", response_model=CompanyResponse)
async def get_company(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get company details by ticker."""
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if not company:
        # Auto-ingest the ticker so direct navigation self-populates.
        # NOTE: the module is app.domains.stock.api.stocks — the earlier
        # `api.v1.stocks` path never existed and raised ModuleNotFoundError on
        # every unknown ticker (audit F01).
        from app.domains.stock.api.stocks import _auto_ingest_ticker
        company = await _auto_ingest_ticker(ticker, db)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
    return CompanyResponse.model_validate(company)
