"""
Events API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.schemas.news import EventListResponse, MarketEventResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=EventListResponse)
async def list_events(
    ticker: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List market events, optionally filtered."""
    query = select(MarketEvent)
    count_query = select(func.count(MarketEvent.id))

    if ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        query = query.where(MarketEvent.company_id == company.id)
        count_query = count_query.where(MarketEvent.company_id == company.id)

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
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single market event."""
    result = await db.execute(select(MarketEvent).where(MarketEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return MarketEventResponse.model_validate(event)