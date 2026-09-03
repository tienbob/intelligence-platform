"""
Company API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, listing/detail show only companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
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
