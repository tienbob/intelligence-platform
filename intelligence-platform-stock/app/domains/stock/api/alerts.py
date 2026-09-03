"""
Alerts API endpoints (Section 42).

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, alerts are only returned for companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.alert import Alert
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.alerts import AlertCreateRequest, AlertListResponse, AlertResponse
from app.shared.identity import company_is_scoped, requester_scope, scoped_where

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/", response_model=AlertResponse, status_code=201)
async def create_alert(
    request: AlertCreateRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert (Section 42) — scoped to the requesting user's companies."""
    scope = await requester_scope(fastapi_request, db)
    company_id = None
    if request.ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == request.ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company or not company_is_scoped(company.id, scope):
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
        data=alert.data,
    )


@router.get("/", response_model=AlertListResponse)
async def list_alerts(
    request: Request,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List alerts — scoped to the requesting user's companies."""
    scope = await requester_scope(request, db)

    query = select(Alert)
    count_query = select(func.count(Alert.id))

    if unread_only:
        query = query.where(Alert.is_read == False)  # noqa: E712
        count_query = count_query.where(Alert.is_read == False)  # noqa: E712

    query = scoped_where(query, Alert.company_id, scope)
    count_query = scoped_where(count_query, Alert.company_id, scope)

    query = query.order_by(desc(Alert.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    alerts = result.scalars().all()

    total = (await db.execute(count_query)).scalar() or 0

    return AlertListResponse(
        alerts=[AlertResponse.model_validate(a) for a in alerts],
        total=total,
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a single alert — scoped to the requesting user's companies."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    scope = await requester_scope(request, db)
    if not company_is_scoped(alert.company_id, scope):
        raise HTTPException(status_code=404, detail="Alert not found")

    return AlertResponse.model_validate(alert)


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_alert_read(
    alert_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mark an alert as read — scoped to the requesting user's companies."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    scope = await requester_scope(request, db)
    if not company_is_scoped(alert.company_id, scope):
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_read = True
    await db.commit()
    return AlertResponse.model_validate(alert)