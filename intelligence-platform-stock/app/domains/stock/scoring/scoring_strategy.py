"""
Stock domain scoring strategy adapter — implements the domain-neutral
ScoringStrategy protocol (app/intelligence/contracts.py).

This is the pipeline-facing adapter. The production scoring engine used by
the analysis worker lives in ``investment_scoring.py`` (InvestmentScoringEngine).

Weights (target):
    Fundamental       30%
    Valuation         20%
    Growth            15%
    Technical         10%
    Sentiment         10%
    Catalysts         10%
    Risk              -15%
"""

from __future__ import annotations

from typing import Any

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.shared.entities import EntityRef, IntelligenceContext

logger = get_logger(__name__)


class InvestmentScoringStrategy:
    """
    Stock-specific investment scoring strategy.

    Implements the ScoringStrategy protocol so the core pipeline
    can compute scores without knowing about P/E ratios or RSI.

    Delegates to the production ``InvestmentScoringEngine`` (the same
    engine used by ``analysis_worker.recalculate_scores``), so the
    framework-driven path and the worker path produce identical scores
    by construction. The strategy owns the Stock glue: ticker →
    Company row resolution and InvestmentScore row → result-dict mapping.
    """

    async def score(
        self,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute investment score for a company.

        Args:
            entity_ref: Reference to the company (entity_id = ticker)
            context: Built intelligence context
            llm_output: Raw LLM analysis output

        Returns:
            dict with score, confidence, recommendation, and components

        Raises:
            LookupError: If no Company row exists for the ticker.
            Exception: Propagates scoring-engine failures (the caller,
                e.g. the pipeline, decides how to degrade).
        """
        # Late imports keep the module importable without DB models loaded
        # (mirrors the manifest's lazy-import style).
        from app.domains.stock.normalization.companies import EntityResolver
        from app.domains.stock.scoring.investment_scoring import (
            InvestmentScoringEngine,
        )

        ticker = str(entity_ref.entity_id)

        async with async_session_factory() as session:
            company = await EntityResolver(session).resolve(ticker=ticker)
            if company is None:
                raise LookupError(
                    f"No Company record found for ticker '{ticker}'"
                )

            score_row = await InvestmentScoringEngine(session).calculate_score(
                company.id
            )

        result = {
            "metadata": {"score_id": score_row.id},
            "score": float(score_row.overall_score),
            "confidence": (
                float(score_row.confidence)
                if score_row.confidence is not None
                else 0.0
            ),
            "recommendation": score_row.recommendation,
            "components": {
                "fundamental": float(score_row.fundamental_score or 0.0),
                "valuation": float(score_row.valuation_score or 0.0),
                "growth": float(score_row.growth_score or 0.0),
                "technical": float(score_row.technical_score or 0.0),
                "sentiment": float(score_row.sentiment_score or 0.0),
                "catalyst": float(score_row.catalyst_score or 0.0),
                "risk": float(score_row.risk_score or 0.0),
            },
        }

        # Carry scoring-model provenance when present (Phase 6 metadata).
        if getattr(score_row, "scoring_model", None):
            result["scoring_model"] = score_row.scoring_model
        if getattr(score_row, "scoring_version", None):
            result["scoring_version"] = score_row.scoring_version

        logger.info(
            "Framework scoring for %s: %.1f (%s)",
            ticker,
            result["score"],
            result["recommendation"],
        )
        return result