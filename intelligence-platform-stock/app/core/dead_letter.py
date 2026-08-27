"""
Dead-letter handling (Phase 8, Section 36).

Implements a dead-letter queue for permanently failed jobs with
retry tracking, inspection, and replay capabilities.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class DeadLetterRecord:
    """A record in the dead-letter queue."""

    def __init__(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, Any],
        failure_reason: str,
        attempts: int,
        provider: str | None = None,
    ):
        self.job_id = job_id
        self.job_type = job_type
        self.payload = payload
        self.failure_reason = failure_reason
        self.attempts = attempts
        self.provider = provider
        self.created_at = datetime.now(timezone.utc)
        self.replayed = False
        self.replayed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "failure_reason": self.failure_reason,
            "attempts": self.attempts,
            "provider": self.provider,
            "created_at": self.created_at.isoformat(),
            "replayed": self.replayed,
            "replayed_at": self.replayed_at.isoformat() if self.replayed_at else None,
        }


class DeadLetterQueue:
    """
    In-memory dead-letter queue.

    Jobs that fail permanently are added here for operator inspection
    and replay. In production this would be backed by PostgreSQL.
    """

    def __init__(self, max_attempts: int | None = None):
        self.max_attempts = max_attempts or settings.DEAD_LETTER_MAX_ATTEMPTS
        self._records: dict[str, DeadLetterRecord] = {}
        self._lock = asyncio.Lock()

    async def add(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, Any],
        failure_reason: str,
        attempts: int,
        provider: str | None = None,
    ) -> DeadLetterRecord:
        """Add a failed job to the dead-letter queue."""
        record = DeadLetterRecord(
            job_id=job_id,
            job_type=job_type,
            payload=payload,
            failure_reason=failure_reason,
            attempts=attempts,
            provider=provider,
        )
        async with self._lock:
            self._records[job_id] = record
        logger.error(
            "Job %s (%s) moved to dead-letter queue after %d attempts: %s",
            job_id,
            job_type,
            attempts,
            failure_reason,
        )
        return record

    async def get(self, job_id: str) -> DeadLetterRecord | None:
        """Get a dead-letter record by job ID."""
        async with self._lock:
            return self._records.get(job_id)

    async def list(self, job_type: str | None = None) -> list[DeadLetterRecord]:
        """List dead-letter records, optionally filtered by job type."""
        async with self._lock:
            records = list(self._records.values())
        if job_type:
            records = [r for r in records if r.job_type == job_type]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    async def replay(self, job_id: str) -> DeadLetterRecord | None:
        """Mark a dead-letter record as replayed (for operator retry)."""
        async with self._lock:
            record = self._records.get(job_id)
            if record:
                record.replayed = True
                record.replayed_at = datetime.now(timezone.utc)
            return record

    async def remove(self, job_id: str) -> bool:
        """Remove a record from the dead-letter queue."""
        async with self._lock:
            return self._records.pop(job_id, None) is not None

    async def count(self) -> int:
        """Return the number of records in the queue."""
        async with self._lock:
            return len(self._records)

    def should_dead_letter(self, attempts: int) -> bool:
        """Check if a job should be moved to the dead-letter queue."""
        return attempts >= self.max_attempts


# Global dead-letter queue instance
dead_letter_queue = DeadLetterQueue()