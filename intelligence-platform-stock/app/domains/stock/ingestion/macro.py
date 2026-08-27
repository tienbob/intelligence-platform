"""
Macro data ingestion (Section 16).

Ingests macroeconomic indicators from FRED, stores raw payloads,
then normalizes into canonical economic_indicators.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.macro import EconomicIndicator
from app.domains.stock.models.raw import RawMacroData
from app.domains.stock.providers import FREDProvider, ProviderError
from app.domains.stock.validation.freshness import check_freshness, classify_freshness
from app.domains.stock.validation.schema import validate_economic_indicator

logger = get_logger(__name__)


class MacroIngestion:
    """Ingests macroeconomic data from FRED."""

    def __init__(self, session: AsyncSession, provider: FREDProvider | None = None):
        self.session = session
        self.provider = provider or FREDProvider()

    async def _store_raw(self, indicator: str, payload: dict[str, Any]) -> RawMacroData:
        raw = RawMacroData(
            provider="FRED",
            endpoint="/series/observations",
            indicator=indicator,
            retrieved_at=datetime.now(timezone.utc),
            payload=payload,
        )
        self.session.add(raw)
        await self.session.flush()
        return raw

    async def ingest_indicator(self, indicator_id: str) -> dict[str, Any]:
        """
        Ingest a single macro indicator.

        Returns a structured result:
            {
                "success": bool,
                "inserted": int,
                "skipped": int,
                "error": str | None,
            }
        """
        try:
            observations = await self.provider.get_indicator(indicator_id)
            raw = await self._store_raw(indicator_id, {"observations": observations})

            retrieved_at = raw.retrieved_at
            data_age_seconds = (datetime.now(timezone.utc) - retrieved_at).total_seconds()
            freshness = classify_freshness(data_age_seconds)
            is_fresh = check_freshness(retrieved_at)
            if not is_fresh:
                logger.warning(
                    "Macro indicator data freshness check failed for %s: age=%.0fs, freshness=%s",
                    indicator_id,
                    data_age_seconds,
                    freshness.value,
                )

            count = 0
            skipped = 0
            for obs in observations:
                ts = obs.get("timestamp")
                if isinstance(ts, str) or isinstance(ts, (int, float)):
                    ts = self.provider._normalize_timestamp(ts)
                else:
                    ts = None
                if ts is None:
                    logger.warning(
                        "Skipping macro observation with invalid timestamp for %s: %r",
                        indicator_id,
                        obs.get("timestamp"),
                    )
                    skipped += 1
                    continue

                value = obs.get("value")
                if value is None:
                    logger.debug("Skipping macro observation with missing value for %s at %s", indicator_id, ts)
                    skipped += 1
                    continue

                validation_data = {
                    "indicator": indicator_id,
                    "timestamp": ts,
                    "value": value,
                    "unit": obs.get("unit"),
                    "source": "FRED",
                }
                validation_result = validate_economic_indicator(validation_data)
                if not validation_result:
                    logger.warning(
                        "Skipping invalid macro observation for %s at %s: %s",
                        indicator_id,
                        ts,
                        validation_result.errors,
                    )
                    skipped += 1
                    continue

                insert_stmt = insert(EconomicIndicator).values(
                    indicator=indicator_id,
                    timestamp=ts,
                    value=value,
                    unit=obs.get("unit"),
                    source="FRED",
                    frequency=obs.get("frequency"),
                ).on_conflict_do_nothing(
                    index_elements=["indicator", "timestamp"]
                )
                result = await self.session.execute(insert_stmt)
                if result.rowcount == 0:
                    logger.debug(
                        "Skipping duplicate macro observation for %s at %s",
                        indicator_id,
                        ts,
                    )
                    skipped += 1
                    continue
                count += 1

            await self.session.commit()
            logger.info(
                "Ingested %d data points (skipped %d) for indicator %s",
                count,
                skipped,
                indicator_id,
            )
            return {"success": True, "inserted": count, "skipped": skipped, "error": None}

        except ProviderError as exc:
            logger.error("Failed to ingest macro indicator %s: %s", indicator_id, exc)
            return {"success": False, "inserted": 0, "skipped": 0, "error": str(exc)}

        except Exception as exc:
            # One bad indicator must not abort the whole ingestion run.
            logger.error(
                "Unexpected error ingesting macro indicator %s: %s",
                indicator_id,
                exc,
                exc_info=True,
            )
            return {"success": False, "inserted": 0, "skipped": 0, "error": str(exc)}

    async def ingest_all_indicators(self) -> dict[str, dict[str, Any]]:
        """Ingest all configured FRED indicators.

        Returns a per-indicator result map; a failure in one indicator
        does not abort the others.
        """
        from app.domains.stock.providers.fred import FRED_SERIES

        results: dict[str, dict[str, Any]] = {}
        for indicator_id in FRED_SERIES:
            results[indicator_id] = await self.ingest_indicator(indicator_id)
        return results
