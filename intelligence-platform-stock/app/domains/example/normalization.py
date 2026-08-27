"""Example domain normalizer — passes through product data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.shared.entities import EntityRef, Observation


class ProductNormalizer:
    """Normalize raw product data into observations."""

    async def normalize(
        self, raw_data: list[dict[str, Any]], entity_ref: EntityRef
    ) -> list[Observation]:
        observations: list[Observation] = []
        for item in raw_data:
            observations.append(
                Observation(
                    entity_ref=entity_ref,
                    observed_at=datetime.now(timezone.utc),
                    data=item,
                    source="product_db",
                )
            )
        return observations