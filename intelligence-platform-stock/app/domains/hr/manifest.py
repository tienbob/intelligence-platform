"""
HR Domain Manifest — wires the HR domain into the intelligence platform.

This is a PLACEHOLDER domain pack. All methods return controlled
"not implemented" responses so the platform can start and discover
this domain without errors. Implement each method to activate.

To activate:
    1. Implement the provider, context builder, scoring, and API modules
    2. Set INTELLIGENCE_DOMAINS=stock,hr (or omit to enable all)
    3. Restart
"""

from __future__ import annotations

from typing import Any

DOMAIN_NAME = "hr"
DOMAIN_VERSION = "0.1.0"


class HRDomain:
    """HR Intelligence domain module — PLACEHOLDER."""

    name = DOMAIN_NAME
    version = DOMAIN_VERSION

    def get_providers(self) -> dict[str, Any]:
        """
        Return HR-specific data providers.

        Implement providers for:
        - ATS (Applicant Tracking Systems: Greenhouse, Lever, Workday)
        - Job Boards (LinkedIn, Indeed, Glassdoor)
        - Professional Networks (LinkedIn API)
        - Salary Data (Levels.fyi, Glassdoor, Radford)
        - Skills Taxonomies (ESCO, O*NET)
        """
        from app.domains.hr.providers import (
            ATSProvider,
            JobBoardProvider,
            SalaryDataProvider,
            SkillsTaxonomyProvider,
        )

        return {
            "ats": ATSProvider(),
            "job_board": JobBoardProvider(),
            "salary": SalaryDataProvider(),
            "skills": SkillsTaxonomyProvider(),
        }

    def get_normalizers(self) -> dict[str, Any]:
        """Return HR-specific data normalizers."""
        from app.domains.hr.normalization import (
            CandidateNormalizer,
            JobNormalizer,
            SkillNormalizer,
        )

        return {
            "candidate": CandidateNormalizer(),
            "job": JobNormalizer(),
            "skill": SkillNormalizer(),
        }

    def get_context_builder(self) -> Any:
        """
        Return the HR-specific context builder.

        Builds structured context for LLM analysis including:
        candidate profile, job requirements, skills match,
        salary benchmarks, market demand, culture fit indicators.
        """
        from app.domains.hr.context_builder import HRContextBuilder

        return HRContextBuilder()

    def get_scoring_strategy(self) -> Any:
        """
        Return the HR-specific candidate/job scoring strategy.

        Computes: skills match (35%) + experience fit (25%) +
        salary alignment (15%) + culture indicators (15%) +
        market demand (10%).
        """
        from app.domains.hr.scoring import HRScoringStrategy

        return HRScoringStrategy()

    def get_intelligence_tasks(self) -> list[Any]:
        """Return HR-specific background tasks."""
        from app.domains.hr.workers import (
            IngestCandidateDataTask,
            IngestJobMarketDataTask,
            IngestSalaryBenchmarksTask,
            RecalculateCandidateScoresTask,
            UpdateSkillsTaxonomyTask,
        )

        return [
            IngestCandidateDataTask(),
            IngestJobMarketDataTask(),
            IngestSalaryBenchmarksTask(),
            RecalculateCandidateScoresTask(),
            UpdateSkillsTaxonomyTask(),
        ]

    def get_api_router(self):
        """Return the HR-specific FastAPI router."""
        from app.domains.hr.api import hr_router

        return hr_router

    def get_prompts(self) -> PromptRegistry:
        """Return HR-specific LLM prompt templates."""
        from pathlib import Path

        from app.intelligence.prompts import SimplePromptRegistry

        prompts_dir = Path(__file__).parent / "prompts"
        registry = SimplePromptRegistry()
        for prompt_file in prompts_dir.glob("*.txt"):
            registry.register(prompt_file.stem, prompt_file.read_text())
        return registry


DOMAIN = HRDomain()