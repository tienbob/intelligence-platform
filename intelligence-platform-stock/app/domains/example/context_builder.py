"""Example domain context builder — builds product analysis context."""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef, Evidence, IntelligenceContext, Observation


class ExampleContextBuilder:
    """Builds structured intelligence context for product analysis."""

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        product_data = observations[0].data if observations else {}

        return IntelligenceContext(
            entity={
                "name": entity_ref.entity_id,
                "domain": entity_ref.domain,
                "entity_type": entity_ref.entity_type,
            },
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
            domain_snapshots={
                "product_snapshot": {
                    "name": product_data.get("name"),
                    "description": product_data.get("description"),
                    "price": product_data.get("price"),
                    "quality_score": product_data.get("quality_score"),
                    "demand_score": product_data.get("demand_score"),
                    "category": product_data.get("category"),
                },
            },
            metadata={"context_version": "1.0"},
        )