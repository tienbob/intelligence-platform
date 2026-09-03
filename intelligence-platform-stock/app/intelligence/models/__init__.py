"""
Framework-owned SQLAlchemy models (architecture §11.1, Gate 4.2).

The framework owns persistence for framework capabilities. The OLD ``Embedding``
ORM lived under Stock (``app/domains/stock/models/analysis.py``) only because it
originated there during the earlier domain-scaffolding migration; the ORM now
lives here — ``app/intelligence/models/`` — per ``docs/TABLE_OWNERSHIP.md``.

Domains never define or subclass these models. They consume them through the
framework contract surface (``app.intelligence.embeddings``) or generic
injection (e.g. ``PgVectorStore()`` resolving to the framework model).
"""

from app.intelligence.models.embeddings import AsyncVector, Embedding

__all__ = [
    "AsyncVector",
    "Embedding",
]