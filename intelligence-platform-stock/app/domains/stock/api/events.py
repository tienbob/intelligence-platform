"""
Events API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, events are only shown for companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.schemas.news import EventListResponse, MarketEventResponse
from app.shared.identity import (
    company_is_scoped,
    requester_scope,
    scoped_where,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=EventListResponse)
async def list_events(
    request: Request,
    ticker: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List market events, optionally filtered — scoped per requesting user."""
    scope = await requester_scope(request, db)

    query = select(MarketEvent)
    count_query = select(func.count(MarketEvent.id))

    if ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company or not company_is_scoped(company.id, scope):
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        query = query.where(MarketEvent.company_id == company.id)
        count_query = count_query.where(MarketEvent.company_id == company.id)
    elif scope is not None:
        # No ticker but a real user: only events for their granted companies.
        query = scoped_where(query, MarketEvent.company_id, scope)
        count_query = scoped_where(count_query, MarketEvent.company_id, scope)

    if event_type:
        query = query.where(MarketEvent.event_type == event_type)
        count_query = count_query.where(MarketEvent.event_type == event_type)

    query = query.order_by(desc(MarketEvent.event_date)).offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    total = (await db.execute(count_query)).scalar() or 0

    return EventListResponse(
        events=[MarketEventResponse.model_validate(e) for e in events],
        total=total,
    )


@router.get("/{event_id}", response_model=MarketEventResponse)
async def get_event(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a single market event — scoped to the requesting user's companies."""
    result = await db.execute(select(MarketEvent).where(MarketEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    scope = await requester_scope(request, db)
    if not company_is_scoped(event.company_id, scope):
        raise HTTPException(status_code=404, detail="Event not found")

    return MarketEventResponse.model_validate(event)