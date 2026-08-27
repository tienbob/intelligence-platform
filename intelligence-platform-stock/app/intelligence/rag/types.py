"""
Retrieval result types — domain-neutral.

The generic RAG core does not know whether a retrieved document is a news
article, an SEC filing, an employee review, a candidate profile, or a
property listing. It only knows ids, content, scores, and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedDocument:
    """A single retrieval result from the vector store."""

    id: int | str
    content: str
    score: float  # cosine similarity (or fused keyword score for hybrid)
    entity_type: str = ""
    entity_id: int | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Tolerate malformed metadata from the store (NULL columns, etc.)
        if self.metadata is None or not isinstance(self.metadata, dict):
            self.metadata = {}

    def to_legacy_dict(self) -> dict[str, Any]:
        """
        Convert to the flat dict shape the Stock RAG service has always
        returned (id/entity_type/entity_id/content/metadata/similarity),
        preserving backward compatibility for existing consumers.
        """
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "content": self.content,
            "metadata": self.metadata,
            "similarity": self.score,
        }

    @classmethod
    def from_legacy_dict(cls, d: dict[str, Any]) -> "RetrievedDocument":
        return cls(
            id=d["id"],
            content=d.get("content", ""),
            score=float(d.get("similarity", 0.0)),
            entity_type=d.get("entity_type", ""),
            entity_id=d.get("entity_id"),
            metadata=d.get("metadata") or {},
        )


@dataclass
class RetrievalFilters:
    """
    Domain-agnostic retrieval constraints applied as SQL against the
    ``embeddings`` table.

    Generic vocabulary only:
      - entity_types: which kinds of documents to include
      - metadata_equals: exact matches on JSONB metadata fields
        (e.g. {"company_id": "123"} — values are cast to str)
      - metadata_min: minimum numeric value on JSONB metadata fields
        (e.g. {"importance": 0.5}; missing fields count as 0)
      - date_from / date_to: inclusive bounds on ``date_metadata_field``
    """

    entity_types: list[str] = field(default_factory=list)
    metadata_equals: dict[str, str] = field(default_factory=dict)
    metadata_min: dict[str, float] = field(default_factory=dict)
    date_from: Any | None = None  # datetime | None
    date_to: Any | None = None
    date_metadata_field: str = "published_at"

    def is_empty(self) -> bool:
        """True when no constraint is set."""
        return not (
            self.entity_types
            or self.metadata_equals
            or self.metadata_min
            or self.date_from is not None
            or self.date_to is not None
        )