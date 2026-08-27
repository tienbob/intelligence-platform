"""
HR domain data normalizers — PLACEHOLDER.

Implement normalizers to transform raw provider data into
domain-neutral Observations.
"""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, Observation


class CandidateNormalizer:
    """Normalize raw candidate data into observations."""

    async def normalize(
        self, raw_data: list[dict[str, Any]], entity_ref: EntityRef
    ) -> list[Observation]:
        raise NotImplementedError(
            "Implement candidate data normalization: extract skills, experience, "
            "education, salary expectations from raw ATS/Job Board data."
        )


class JobNormalizer:
    """Normalize raw job data into observations."""

    async def normalize(
        self, raw_data: list[dict[str, Any]], entity_ref: EntityRef
    ) -> list[Observation]:
        raise NotImplementedError(
            "Implement job data normalization: extract requirements, salary range, "
            "location, remote policy from raw job board data."
        )


class SkillNormalizer:
    """Normalize raw skill taxonomy data into observations."""

    async def normalize(
        self, raw_data: list[dict[str, Any]], entity_ref: EntityRef
    ) -> list[Observation]:
        raise NotImplementedError(
            "Implement skill taxonomy normalization: map raw skills to "
            "standardized taxonomy (ESCO/O*NET)."
        )