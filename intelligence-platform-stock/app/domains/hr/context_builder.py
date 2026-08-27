"""
HR domain context builder — PLACEHOLDER.

Builds structured intelligence context for HR analysis:
candidate evaluation, job matching, salary benchmarking.

Implement the build() method to construct IntelligenceContext
from candidate profiles, job requirements, skills data, and market benchmarks.
"""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation


class HRContextBuilder:
    """
    Builds structured intelligence context for HR analysis.

    Sections to implement:
        - Candidate profile (skills, experience, education, achievements)
        - Job requirements (must-have skills, nice-to-have, level, location)
        - Skills match analysis (overlap, gaps, proficiency alignment)
        - Salary benchmarks (market range, percentile data, equity norms)
        - Market demand (hiring velocity, competition for talent)
        - Culture indicators (values alignment, work style preferences)
        - RAG context (similar candidate profiles, past hiring decisions)
    """

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        """
        Build the full intelligence context for an HR entity.

        Args:
            entity_ref: Reference to candidate, job, or skill entity
            evidence: Collected evidence from providers
            observations: Normalized observations
            rag_context: RAG retrieval results
            **kwargs: Additional domain-specific parameters

        Returns:
            IntelligenceContext ready for LLM consumption
        """
        raise NotImplementedError(
            "HR context builder not implemented. "
            "Implement candidate profile extraction, job requirement parsing, "
            "skills matching, salary benchmarking, and culture fit analysis. "
            "See stock/context_builder.py for the pattern to follow."
        )