"""
HR domain background workers.

Tasks that are not yet implemented are explicitly disabled so the
domain-agnostic scheduler does not execute placeholder implementations.

Each task exposes:
    - name: str
    - interval_minutes: int
    - run_immediately: bool
    - enabled: bool
    - async execute() -> None
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)


class IngestCandidateDataTask:
    """Ingest candidate data from ATS and job boards."""

    name = "Ingest candidate data"
    interval_minutes = 1440  # 24 hours
    run_immediately = True
    enabled = False

    async def execute(self) -> None:
        raise NotImplementedError(
            "Implement candidate data ingestion from ATS (Greenhouse/Lever/Workday)."
        )


class IngestJobMarketDataTask:
    """Ingest job market data from job boards."""

    name = "Ingest job market data"
    interval_minutes = 720  # 12 hours
    run_immediately = True
    enabled = False

    async def execute(self) -> None:
        raise NotImplementedError(
            "Implement job market data ingestion from job boards "
            "(LinkedIn/Indeed/Glassdoor)."
        )


class IngestSalaryBenchmarksTask:
    """Ingest salary benchmark data."""

    name = "Ingest salary benchmarks"
    interval_minutes = 10080  # weekly
    run_immediately = True
    enabled = False

    async def execute(self) -> None:
        raise NotImplementedError(
            "Implement salary benchmark ingestion from "
            "Levels.fyi/Glassdoor."
        )


class RecalculateCandidateScoresTask:
    """Recalculate candidate-job fit scores."""

    name = "Recalculate candidate scores"
    interval_minutes = 1440  # 24 hours
    run_immediately = True
    enabled = False

    async def execute(self) -> None:
        raise NotImplementedError(
            "Implement candidate scoring recalculation."
        )


class UpdateSkillsTaxonomyTask:
    """Update skills taxonomy from ESCO/O*NET."""

    name = "Update skills taxonomy"
    interval_minutes = 43200  # monthly
    run_immediately = True
    enabled = False

    async def execute(self) -> None:
        raise NotImplementedError(
            "Implement skills taxonomy update from ESCO/O*NET."
        )
    