"""Example domain provider — returns mock product data."""

from __future__ import annotations

from typing import Any

from app.shared.entities import EntityRef


class ProductProvider:
    """Mock product data provider for platform validation."""

    provider_name = "product_db"

    async def fetch(self, entity_ref: EntityRef, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": entity_ref.entity_id,
                "description": f"Product {entity_ref.entity_id}",
                "price": 99.99,
                "quality_score": 85,
                "demand_score": 72,
                "category": "electronics",
            }
        ]

    async def health_check(self) -> bool:
        return True