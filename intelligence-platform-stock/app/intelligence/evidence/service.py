"""
Generic evidence service — domain-agnostic facade.

Combines the observation boundary (observations → evidence) with the
attribution registry (claim ↔ source). Domains decide what counts as
meaningful evidence; the framework owns the mechanics.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.logging import get_logger
from app.intelligence.evidence.attribution import EvidenceAttributor
from app.intelligence.evidence.types import EvidencePackage, RagContext
from app.intelligence.observations import (
    evidence_from_vendor_records,
    make_observation,
    observations_to_evidence,
)
from app.shared.entities import EntityRef, Evidence, Observation

logger = get_logger(__name__)


class EvidenceService:
    """
    Domain-agnostic evidence facade.

    Usage:
        svc = EvidenceService()
        evidence = svc.observations_to_evidence(observations)
        package = svc.build_package(entity_ref, records, source="massive")
    """

    def __init__(self) -> None:
        self.attributor = EvidenceAttributor()

    # ── Observation boundary ────────────────────────────────────

    def make_observation(
        self,
        entity_ref: EntityRef,
        *,
        source: str,
        data: dict[str, Any],
        kind: str = "",
        confidence: float = 1.0,
    ) -> Observation:
        """Build a generic observation (see ``observations`` module)."""
        return make_observation(
            entity_ref, source=source, data=data, kind=kind, confidence=confidence
        )

    async def observations_to_evidence(
        self, observations: Iterable[Observation]
    ) -> list[Evidence]:
        """Convert observations into source-backed evidence."""
        return observations_to_evidence(observations)

    async def evidence_from_vendor(
        self,
        entity_ref: EntityRef,
        *,
        source: str,
        records: Iterable[dict[str, Any]],
        kind: str = "",
    ) -> list[Evidence]:
        """Convert vendor response records directly into evidence."""
        return evidence_from_vendor_records(
            entity_ref, source=source, records=records, kind=kind
        )

    # ── Attribution registry ─────────────────────────────────────────

    def register_sources(self, rag_context: RagContext) -> list[dict[str, Any]]:
        """Register RAG sources into the attribution registry."""
        return self.attributor.register_sources(rag_context)

    def build_evidence_package(self, rag_context: RagContext) -> dict[str, Any]:
        """Return the legacy evidence-package dict for a RAG context."""
        return self.attributor.build_evidence_package(rag_context)

    def enrich_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        """Enrich a claim with its resolved sources."""
        return self.attributor.enrich_claim_with_sources(claim)

    def claim_is_supported(self, claim: dict[str, Any]) -> bool:
        """Whether a claim's evidence_ids resolve to registered sources."""
        return self.attributor.validate_claim_evidence(claim)

    # ── Structured package (richer API) ───────────────────────────────

    def build_package(self, rag_context: RagContext) -> EvidencePackage:
        """Return the richer EvidencePackage object (not the legacy dict)."""
        sources = self.attributor.register_sources(rag_context)
        return EvidencePackage.from_source_dicts(sources)