"""
Embedding core types — domain-neutral records and vectors.

The framework moves vectors around; it does not know whether the content
is a news article, an SEC filing, or an employee review.

``VectorRecord`` carries the **generic identity** required by the
``embeddings`` schema (architecture §11.1):

    domain       → which domain owns the entity          (e.g. "stock")
    entity_type  → what kind of entity it is             (e.g. "news")
    entity_id    → the entity's id in its domain table   (e.g. news.id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# A raw embedding vector as returned by any provider.
EmbeddingVector = list[float]


@dataclass
class VectorRecord:
    """A unit of embedding work: generic identity + content + vector."""

    domain: str
    entity_type: str
    entity_id: int | str
    content: str
    vector: EmbeddingVector = field(default_factory=list)
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_embedded(self) -> bool:
        return bool(self.vector)


def chunked(items: list, size: int) -> list[list]:
    """Split a list into consecutive chunks of at most ``size``."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]