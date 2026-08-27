"""Example domain scoring — trivial product scoring for platform validation."""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, IntelligenceContext


class ExampleScoringStrategy:
    """Scores products based on quality, price competitiveness, and demand."""

    async def score(
        self,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = context.domain_snapshots.get("product_snapshot", {})
        quality = snapshot.get("quality_score", 50)
        demand = snapshot.get("demand_score", 50)
        price = snapshot.get("price", 100)

        # Simple scoring: quality 40% + demand 30% + price-competitiveness 30%
        price_score = max(0, min(100, 100 - (price / 2)))  # lower price = higher score
        overall = quality * 0.4 + demand * 0.3 + price_score * 0.3

        if overall >= 80:
            recommendation = "STRONG_BUY"
        elif overall >= 60:
            recommendation = "BUY"
        elif overall >= 40:
            recommendation = "HOLD"
        else:
            recommendation = "AVOID"

        return {
            "score": round(overall, 1),
            "confidence": 0.7,
            "recommendation": recommendation,
            "components": {
                "quality": quality,
                "demand": demand,
                "price_competitiveness": round(price_score, 1),
            },
        }