"""
Shared mixins and utilities for ORM models.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProvenanceMixin:
    """
    Adds data-provenance columns required by Section 12 of the architecture.

    Every important data point should carry source metadata so the system
    can answer: "Where did this number come from?"
    """

    source: Mapped[str | None] = mapped_column(nullable=True)
    source_id: Mapped[str | None] = mapped_column(nullable=True, index=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_version: Mapped[str | None] = mapped_column(nullable=True)


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)