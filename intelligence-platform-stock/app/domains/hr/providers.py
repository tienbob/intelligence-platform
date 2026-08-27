"""
HR domain providers — PLACEHOLDER.

Implement these providers to fetch data from HR-specific sources.
Each provider must implement the Provider protocol:
    - provider_name: str
    - async fetch(entity_ref, **kwargs) -> list[dict]
    - async health_check() -> bool
"""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef


class ATSProvider:
    """
    Applicant Tracking System provider.

    Implement integrations with:
    - Greenhouse API (https://developers.greenhouse.io/)
    - Lever API (https://hire.lever.co/developer)
    - Workday API
    """

    provider_name = "ats"

    async def fetch(self, entity_ref: EntityRef, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch candidate data from ATS.

        Args:
            entity_ref: EntityRef(domain="hr", entity_type="candidate", entity_id="cand-123")
        """
        raise NotImplementedError(
            "ATS provider not implemented. "
            "Integrate with Greenhouse/Lever/Workday API to fetch candidate profiles, "
            "application history, interview feedback, and offer data."
        )

    async def health_check(self) -> bool:
        return False  # Not configured


class JobBoardProvider:
    """
    Job board data provider.

    Implement integrations with:
    - LinkedIn Jobs API
    - Indeed API
    - Glassdoor API
    """

    provider_name = "job_board"

    async def fetch(self, entity_ref: EntityRef, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch job market data.

        Args:
            entity_ref: EntityRef(domain="hr", entity_type="job", entity_id="job-456")
        """
        raise NotImplementedError(
            "Job board provider not implemented. "
            "Integrate with LinkedIn/Indeed/Glassdoor APIs to fetch job listings, "
            "market demand data, and company reviews."
        )

    async def health_check(self) -> bool:
        return False


class SalaryDataProvider:
    """
    Salary benchmarking provider.

    Implement integrations with:
    - Levels.fyi API
    - Glassdoor Salary API
    - Radford / Aon surveys
    """

    provider_name = "salary"

    async def fetch(self, entity_ref: EntityRef, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch salary benchmarks for a role/location.

        Args:
            entity_ref: EntityRef(domain="hr", entity_type="salary_benchmark", entity_id="swe-sf")
        """
        raise NotImplementedError(
            "Salary data provider not implemented. "
            "Integrate with Levels.fyi/Glassdoor to fetch salary percentiles, "
            "equity ranges, and total compensation benchmarks."
        )

    async def health_check(self) -> bool:
        return False


class SkillsTaxonomyProvider:
    """
    Skills taxonomy provider.

    Implement integrations with:
    - ESCO (European Skills/Competences/Qualifications/Occupations)
    - O*NET (Occupational Information Network)
    - Lightcast (formerly Emsi Burning Glass)
    """

    provider_name = "skills"

    async def fetch(self, entity_ref: EntityRef, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch skills taxonomy data.

        Args:
            entity_ref: EntityRef(domain="hr", entity_type="skill", entity_id="python")
        """
        raise NotImplementedError(
            "Skills taxonomy provider not implemented. "
            "Integrate with ESCO/O*NET to fetch skill definitions, "
            "categories, proficiency levels, and related skills."
        )

    async def health_check(self) -> bool:
        return False