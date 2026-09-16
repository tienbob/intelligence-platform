"""
Alerts API endpoints (Section 42).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.alert import Alert
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.alerts import AlertCreateRequest, AlertListResponse, AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/", response_model=AlertResponse, status_code=201)
async def create_alert(
    request: AlertCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert (Section 42)."""
    company_id = None
    if request.ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == request.ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {request.ticker} not found")
        company_id = company.id

    alert = Alert(
        company_id=company_id,
        alert_type=request.alert_type,
        severity=request.severity,
        message=request.message,
        data=request.data,
        is_read=False,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    return AlertResponse(
        id=alert.id,
        ticker=request.ticker.upper() if request.ticker else None,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
    )


@router.get("/", response_model=AlertListResponse)
async def list_alerts(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List alerts (lean rows: what the FE feed renders)."""
    query = (
        select(Alert, Company.ticker)
        .join(Company, Company.id == Alert.company_id, isouter=True)
    )

    if unread_only:
        query = query.where(Alert.is_read == False)  # noqa: E712

    query = query.order_by(desc(Alert.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    return AlertListResponse(
        alerts=[
            AlertResponse(
                id=a.id,
                ticker=t,
                alert_type=a.alert_type,
                severity=a.severity,
                message=a.message,
            )
            for a, t in rows
        ],
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single alert."""
    result = await db.execute(
        select(Alert, Company.ticker)
        .join(Company, Company.id == Alert.company_id, isouter=True)
        .where(Alert.id == alert_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert, ticker = row
    return AlertResponse(
        id=alert.id,
        ticker=ticker,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
    )


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_alert_read(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Mark an alert as read."""
    result = await db.execute(
        select(Alert, Company.ticker)
        .join(Company, Company.id == Alert.company_id, isouter=True)
        .where(Alert.id == alert_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert, ticker = row
    alert.is_read = True
    await db.commit()
    return AlertResponse(
        id=alert.id,
        ticker=ticker,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
    )