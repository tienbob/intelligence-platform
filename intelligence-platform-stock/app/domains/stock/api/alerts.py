"""
Alerts API endpoints (Section 42).

User-scoped (2026-09-30, audit F1/S2): user-created alerts carry the
caller's ``user_id`` and are visible only to their owner; system/scheduler
alerts (``user_id IS NULL``) remain visible to everyone. Mutating actions
(mark read) follow the analysis precedent — only the owner (or admin) may
dismiss; cross-user/system rows return the same 404 so existence isn't
leaked.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select, exists, and_, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_actor, is_admin_actor, owns_row, visible_to_actor
from app.domains.stock.models.alert import Alert, AlertRead
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.alerts import AlertCreateRequest, AlertListResponse, AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _visible(actor):
    if is_admin_actor(actor):
        return True
    return and_(visible_to_actor(Alert.user_id, actor), Alert.legacy_private.is_(False))


def _can_manage(alert: Alert, actor: dict) -> bool:
    """Only the author of a private row may mutate it.

    Shared system rows (``user_id IS NULL``) and anything grandfathered as
    ``legacy_private`` are strictly view-only — even for admins — because
    their old ``is_read`` writes were shared writes. Each viewer manages
    their own receipt via their own row or the alert_reads table.
    """
    if alert.user_id is None or alert.legacy_private:
        return False
    return owns_row(alert.user_id, actor)


def _read(actor):
    receipt = exists(select(AlertRead.alert_id).where(AlertRead.alert_id == Alert.id, AlertRead.user_id == (actor.get("user_id") or 0)))
    # Preserve historic read state only for the owner, never for all viewers.
    return or_(receipt, and_(Alert.user_id == actor.get("user_id"), Alert.user_id.is_not(None), Alert.is_read.is_(True)))


def _response(alert, ticker, actor, read):
    return AlertResponse(id=alert.id, ticker=ticker, alert_type=alert.alert_type,
                         severity=alert.severity, message=alert.message,
                         can_manage=_can_manage(alert, actor), is_read=bool(read))


@router.post("/", response_model=AlertResponse, status_code=201)
async def create_alert(
    request: AlertCreateRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert (Section 42). User-bound to the caller."""
    actor = get_actor(fastapi_request)
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
        user_id=actor.get("user_id"),
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
        can_manage=_can_manage(alert, actor),
        is_read=alert.is_read,
    )


@router.get("/", response_model=AlertListResponse)
async def list_alerts(
    fastapi_request: Request,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List alerts (lean rows: what the FE feed renders).

    User-bound: own rows + system (user_id IS NULL) rows — mirrors the
    analyses/backtest_runs visibility rule.
    """
    actor = get_actor(fastapi_request)
    query = select(Alert, Company.ticker, _read(actor).label("viewer_read")).join(
        Company, Company.id == Alert.company_id, isouter=True).where(_visible(actor))
    if unread_only:
        query = query.where(~_read(actor))
    result = await db.execute(query.order_by(desc(Alert.created_at), desc(Alert.id)).offset(offset).limit(limit))
    return AlertListResponse(alerts=[_response(a, t, actor, read) for a, t, read in result.all()])


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: int, fastapi_request: Request, db: AsyncSession = Depends(get_db)):
    """Get a single alert (owner/system row, or admin)."""
    actor = get_actor(fastapi_request)
    result = await db.execute(select(Alert, Company.ticker, _read(actor)).join(
        Company, Company.id == Alert.company_id, isouter=True).where(Alert.id == alert_id, _visible(actor)))
    row = result.one_or_none()
    if not row or not _can_manage(row[0], actor):
        raise HTTPException(status_code=404, detail="Alert not found")
    return _response(row[0], row[1], actor, row[2])


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_alert_read(alert_id: int, fastapi_request: Request, db: AsyncSession = Depends(get_db)):
    actor = get_actor(fastapi_request)
    result = await db.execute(select(Alert, Company.ticker).join(
        Company, Company.id == Alert.company_id, isouter=True).where(Alert.id == alert_id, _visible(actor)))
    row = result.one_or_none()
    if not row or not _can_manage(row[0], actor):
        raise HTTPException(status_code=404, detail="Alert not found")
    alert, ticker = row
    await db.execute(insert(AlertRead).values(alert_id=alert.id, user_id=actor.get("user_id") or 0).on_conflict_do_nothing())
    await db.commit()
    return _response(alert, ticker, actor, True)
