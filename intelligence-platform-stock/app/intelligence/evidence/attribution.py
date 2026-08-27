"""
Evidence attribution — claim ↔ source relationships.

Every AI-generated claim must be traceable to its source evidence. This
module builds, validates, and enriches that attribution generically.

This is a faithful promotion of Stock's EvidenceAttributor: same method
names, same return shapes (dict-based) so existing callers observe no
behavior change. The framework owns the mechanics; the domain owns what
counts as meaningful evidence.
"""

from __future__ import annotations

from typing import Any

from app.intelligence.evidence.types import RagContext, source_id_for


class EvidenceAttributor:
    """
    Builds and validates evidence attribution for LLM claims.

    Ensures every claim has source IDs, timestamps, and source types.
    Domain-neutral: knows buckets only by their type label, never imports
    domain code.
    """

    def __init__(self):
        self.source_registry: dict[str, dict[str, Any]] = {}

    def register_sources(
        self, rag_context: RagContext
    ) -> list[dict[str, Any]]:
        """
        Register RAG sources and build the evidence registry.

        Args:
            rag_context: entity_type → list of retrieval result dicts
                (the shape returned by the generic RAG core).

        Returns:
            List of registered evidence-source dicts (stable key:
            ``<entity_type>_<id>``).
        """
        evidence_sources = []

        for entity_type, items in rag_context.items():
            for item in items:
                source_id = source_id_for(entity_type, item["id"])
                source = {
                    "source_id": source_id,
                    "entity_type": entity_type,
                    "entity_id": item["id"],
                    "similarity": item.get("similarity", 0.0),
                    "metadata": item.get("metadata", {}),
                    "published_at": item.get("metadata", {}).get("published_at"),
                }
                self.source_registry[source_id] = source
                evidence_sources.append(source)

        return evidence_sources

    def validate_claim_evidence(self, claim: dict[str, Any]) -> bool:
        """
        Return True if the claim's evidence_ids resolve to registered
        sources (and at least one is present).
        """
        evidence_ids = claim.get("evidence_ids", [])
        if not evidence_ids:
            return False
        return all(eid in self.source_registry for eid in evidence_ids)

    def enrich_claim_with_sources(self, claim: dict[str, Any]) -> dict[str, Any]:
        """Attach resolved source records to a claim."""
        evidence_ids = claim.get("evidence_ids", [])
        resolved = [
            self.source_registry[eid]
            for eid in evidence_ids
            if eid in self.source_registry
        ]
        return {
            **claim,
            "evidence_sources": resolved,
        }

    def build_evidence_package(
        self, rag_context: RagContext
    ) -> dict[str, Any]:
        """
        Build the complete evidence package (dict) for LLM context.

        Return shape (legacy-compatible):
            {evidence_sources, source_count, source_types}
        """
        evidence_sources = self.register_sources(rag_context)
        return {
            "evidence_sources": evidence_sources,
            "source_count": len(evidence_sources),
            "source_types": list({s["entity_type"] for s in evidence_sources}),
        }

    def get_source_metadata(self, source_id: str) -> dict[str, Any] | None:
        """Return the registered source record for ``source_id`` or None."""
        return self.source_registry.get(source_id)