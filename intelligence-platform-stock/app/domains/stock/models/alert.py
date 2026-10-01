"""
Alert model (Section 42).

Trigger alerts when:
    Large price movement, Volume anomaly, Important news,
    Important SEC filing, Earnings release, Risk score changes,
    Investment score changes significantly,
    Portfolio concentration becomes dangerous
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id"), index=True
    )
    # Ownership: user-created alerts carry the caller's Rails user id;
    # NULL = system/scheduler alert (shared, visible to everyone).
    # No FK — the users table is Rails-owned (migration 0018 / Rails mirror).
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    legacy_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<Alert(id={self.id}, type={self.alert_type!r}, severity={self.severity!r})>"

class AlertRead(Base):
    """Each viewer dismisses a shared notification independently."""
    __tablename__ = 'alert_reads'
    alert_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('alerts.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
