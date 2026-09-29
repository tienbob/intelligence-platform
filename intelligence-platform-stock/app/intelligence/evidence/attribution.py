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

# Lexical stopwords for the citation-support check — tokens too generic to
# indicate that a claim is actually derived from the cited document.
_SUPPORT_STOPWORDS = frozenset({
    "the", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "from", "by", "as", "is", "are", "was", "were", "has", "have",
    "had", "its", "this", "that", "will", "would", "could", "should",
    "may", "can", "new", "vs", "versus", "per", "over", "about",
})


def _content_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens of length >= 3, minus stopwords."""
    import re

    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(tok) >= 3 and tok not in _SUPPORT_STOPWORDS
    }


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
                    "content": item.get("content"),
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

    def filter_supported_evidence_ids(self, claim: dict[str, Any]) -> list[str]:
        """
        Keep only cited evidence ids whose content plausibly supports the
        claim (lexical token overlap).

        Citing a *valid but unrelated* document from the evidence set is a
        known LLM failure mode (the ID validator proves the id exists, not
        that the content backs the claim). This is a cheap, deterministic
        lexical check — no embeddings.

        Conservative by design: when the claim or the cited content is too
        short to judge, the citation is kept.
        """
        evidence_ids = list(claim.get("evidence_ids", []))
        if not evidence_ids:
            return evidence_ids
        text = claim.get("claim") or claim.get("cause") or ""
        claim_tokens = _content_tokens(text)
        if len(claim_tokens) < 2:
            return evidence_ids
        kept: list[str] = []
        for eid in evidence_ids:
            source = self.source_registry.get(eid)
            if source is None:
                continue  # unknown ids are the validator's concern
            content_tokens = _content_tokens(source.get("content") or "")
            if len(content_tokens) < 10:
                kept.append(eid)  # too little content to judge
                continue
            if len(claim_tokens & content_tokens) >= 2:
                kept.append(eid)
        return kept