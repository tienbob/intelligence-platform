"""
Evidence core types — domain-neutral provenance records.

The framework tracks *evidence* (a source-backed unit a claim can cite);
domains decide what counts as meaningful evidence for their analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceSource:
    """
    A registered source that a claim can be attributed to.

    ``source_id`` is the stable key (e.g. ``"news_42"``) that claims
    reference in their ``evidence_ids``.
    """

    source_id: str
    entity_type: str
    entity_id: Any
    similarity: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    published_at: str | None = None


@dataclass
class EvidencePackage:
    """The complete set of sources available to attribute claims against."""

    sources: list[EvidenceSource] = field(default_factory=list)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def source_types(self) -> list[str]:
        return list({s.entity_type for s in self.sources})

    @property
    def source_ids(self) -> list[str]:
        return [s.source_id for s in self.sources]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_sources": [
                {
                    "source_id": s.source_id,
                    "entity_type": s.entity_type,
                    "entity_id": s.entity_id,
                    "similarity": s.similarity,
                    "metadata": s.metadata,
                    "published_at": s.published_at,
                }
                for s in self.sources
            ],
            "source_count": self.source_count,
            "source_types": self.source_types,
        }

    @classmethod
    def from_source_dicts(cls, source_dicts: list[dict[str, Any]]) -> "EvidencePackage":
        """Build an EvidencePackage from the dicts produced by an attributor."""
        return cls(
            sources=[
                EvidenceSource(
                    source_id=s["source_id"],
                    entity_type=s["entity_type"],
                    entity_id=s["entity_id"],
                    similarity=s.get("similarity", 0.0),
                    metadata=s.get("metadata", {}),
                    published_at=s.get("published_at"),
                )
                for s in source_dicts
            ]
        )


# RAG contexts map entity_type → list of retrieval result dicts.
RagContext = dict[str, list[dict[str, Any]]]


def source_id_for(entity_type: str, entity_id: Any) -> str:
    """Build the canonical source-id a claim references."""
    return f"{entity_type}_{entity_id}"