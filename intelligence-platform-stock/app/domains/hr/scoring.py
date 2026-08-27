"""
HR domain scoring strategy — PLACEHOLDER.

Computes candidate-job fit scores based on:
    Skills match (35%) + Experience fit (25%) + Salary alignment (15%)
    + Culture indicators (15%) + Market demand (10%)

Implement the score() method with your HR-specific scoring logic.
"""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, IntelligenceContext


class HRScoringStrategy:
    """
    HR-specific candidate/job scoring strategy.

    Implements the ScoringStrategy protocol so the core pipeline
    can compute scores without knowing about skills or salary bands.
    """

    async def score(
        self,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute candidate-job fit score.

        Args:
            entity_ref: Reference to the candidate or job
            context: Built intelligence context
            llm_output: Raw LLM analysis output

        Returns:
            dict with score, confidence, recommendation, and components
        """
        raise NotImplementedError(
            "HR scoring strategy not implemented. "
            "Implement skills matching algorithm, experience fit calculation, "
            "salary alignment scoring, culture fit indicators, and market demand weighting. "
            "See stock/scoring.py for the pattern to follow."
        )