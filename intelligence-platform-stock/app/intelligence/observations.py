"""
Observation boundary — the generic pipeline between provider and evidence.

    Vendor response
          ↓
    Observation   ← produced here (make_observation)
          ↓
    Normalizer (domain) / None
          ↓
    Evidence     ← produced here (observations_to_evidence)

The framework owns the mechanics of turning observations into source-backed
evidence. Domains decide what a "kind" means and how to normalize vendor
responses; they never reimplement this mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.shared.entities import EntityRef, Evidence, Observation


def make_observation(
    entity_ref: EntityRef,
    *,
    source: str,
    data: dict[str, Any],
    kind: str = "",
    observed_at: datetime | None = None,
    freshness: str = "daily",
    confidence: float = 1.0,
) -> Observation:
    """
    Build a generic Observation from a vendor response dict.

    ``source`` should name the actual origin (e.g. "massive", "sec",
    "internal_hr_db") so downstream evidence attribution is meaningful.
    """
    return Observation(
        entity_ref=entity_ref,
        observed_at=observed_at or datetime.now(timezone.utc),
        data=data,
        source=source,
        freshness=freshness,
        kind=kind,
        confidence=confidence,
    )


def observations_to_evidence(
    observations: Iterable[Observation],
) -> list[Evidence]:
    """
    Convert observations into generic, source-backed Evidence.

    Extracts a conventional ``metric`` / ``value`` / ``period`` triple from
    each observation's data for attribution; falls back to the raw data
    when those keys are absent. Confidence is carried through.
    """
    evidence: list[Evidence] = []

    for obs in observations:
        data = obs.data if isinstance(obs.data, dict) else {}
        source_label = obs.source or obs.kind or "observation"

        evidence.append(
            Evidence(
                source_type=source_label,
                source_name=source_label,
                metric=data.get("metric"),
                value=data.get("value", data if data else None),
                period=data.get("period"),
                confidence=obs.confidence,
            )
        )

    return evidence


def evidence_from_vendor_records(
    entity_ref: EntityRef,
    *,
    source: str,
    records: Iterable[dict[str, Any]],
    kind: str = "",
) -> list[Evidence]:
    """
    Convenience: turn a list of vendor response records directly into
    Evidence, skipping explicit Observation construction for simple cases.

    Equivalent to::

        make_observation(...) for each record → observations_to_evidence(...)
    """
    observations = [
        make_observation(entity_ref, source=source, data=record, kind=kind)
        for record in records
    ]
    return observations_to_evidence(observations)