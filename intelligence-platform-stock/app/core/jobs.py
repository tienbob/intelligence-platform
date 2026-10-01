"""Durable PostgreSQL outbox. Reservation and domain row commit atomically.

A worker owns a job with a session advisory lock. Abandoned running jobs are
failed explicitly rather than replaying a potentially billable external call.
Clients may retry as a new action; replaying the original key returns its ID.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from sqlalchemy import DateTime, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.security import IdempotencyReplay, get_actor

class WorkJob(Base):
    __tablename__ = 'work_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    scope: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[str | None] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='queued', nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('scope', 'key', name='uq_work_jobs_scope_key'),)

async def reserve_job(db, request, kind: str, payload: dict[str, Any]):
    key = request.headers.get('Idempotency-Key')
    if key is not None and (not key.strip() or len(key) > 200):
        raise HTTPException(422, 'Idempotency-Key must contain 1–200 characters')
    actor = get_actor(request)
    scope = f"{actor.get('user_id')}:{kind}"
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    job_id = str(uuid.uuid4())
    result = await db.execute(insert(WorkJob).values(
        id=job_id, kind=kind, scope=scope, key=key, fingerprint=fingerprint,
        payload=payload, response={}, status='queued',
    ).on_conflict_do_nothing(constraint='uq_work_jobs_scope_key').returning(WorkJob.id))
    if result.scalar_one_or_none() is None:
        job = (await db.execute(select(WorkJob).where(WorkJob.scope == scope, WorkJob.key == key))).scalar_one()
        if job.fingerprint != fingerprint:
            raise HTTPException(409, 'Idempotency-Key was already used for a different request')
        raise IdempotencyReplay(202, job.response, key)
    return await db.get(WorkJob, job_id)
