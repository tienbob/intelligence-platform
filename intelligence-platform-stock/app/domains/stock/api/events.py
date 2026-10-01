"""
Events API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.schemas.news import EventListItem, EventListResponse, MarketEventResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=EventListResponse)
async def list_events(
    ticker: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List market events (lean rows: what the FE table/timeline renders)."""
    query = select(MarketEvent, Company.ticker).join(
        Company, Company.id == MarketEvent.company_id, isouter=True
    )

    if ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        query = query.where(MarketEvent.company_id == company.id)

    if event_type:
        query = query.where(MarketEvent.event_type == event_type)

    query = query.order_by(desc(MarketEvent.event_date)).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    return EventListResponse(
        events=[
            EventListItem(
                id=e.id,
                ticker=t,
                event_type=e.event_type,
                event_date=e.event_date,
                impact=e.impact,
                impact_score=e.impact_score,
                confidence=e.confidence,
                description=e.description,
            )
            for e, t in rows
        ],
    )


@router.get("/{event_id}", response_model=MarketEventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single market event."""
    result = await db.execute(
        select(MarketEvent, Company.ticker)
        .join(Company, Company.id == MarketEvent.company_id, isouter=True)
        .where(MarketEvent.id == event_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    event, ticker = row
    return MarketEventResponse(
        id=event.id,
        ticker=ticker,
        event_type=event.event_type,
        event_date=event.event_date,
        impact=event.impact,
        impact_score=event.impact_score,
        confidence=event.confidence,
        materiality_score=event.materiality_score,
        effective_weight=event.effective_weight,
        description=event.description,
    )