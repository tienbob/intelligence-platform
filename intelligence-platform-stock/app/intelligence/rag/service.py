"""
Generic RAG service — the framework's retrieval engine.

Knows HOW to search: embed a query, run vector + keyword retrieval,
apply generic filters, merge, deduplicate, and rank. Knows nothing about
domains: buckets (news/filings/candidates/…), entity semantics, and
threshold policies belong to domain layers built on top of this core.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.intelligence.rag.ranking import merge_results, rank_results
from app.intelligence.rag.retrieval import (
    keyword_search,
    prepare_query_embedding,
    similarity_search,
)
from app.intelligence.rag.types import RetrievedDocument, RetrievalFilters

logger = get_logger(__name__)

# An embedder turns a query string into a vector. Provided by the caller
# (typically wrapping the framework embedding service) so this service
# stays independent of any specific embedding provider.
Embedder = Callable[[str], Awaitable[list[float]]]


class GenericRAGService:
    """
    Domain-agnostic retrieval engine over the ``embeddings`` table.

    Usage:
        rag = GenericRAGService(session, embedder=my_embed_fn,
                                embedding_dimensions=1536)
        docs = await rag.search("quarterly revenue growth",
                                filters=RetrievalFilters(entity_types=["news"]),
                                limit=5)
    """

    def __init__(
        self,
        session: AsyncSession,
        embedder: Embedder | None = None,
        embedding_dimensions: int = 0,
        *,
        validate_dimensions: bool = True,
    ):
        self.session = session
        self._embedder = embedder
        self._dimensions = embedding_dimensions
        self._validate_dimensions = validate_dimensions

    async def _embed_query(self, query: str) -> Any:
        if self._embedder is None:
            raise RuntimeError(
                "GenericRAGService requires an embedder to perform vector search"
            )
        embedding = await self._embedder(query)
        if self._validate_dimensions:
            return prepare_query_embedding(embedding, self._dimensions)
        return prepare_query_embedding(embedding, len(embedding))

    async def search(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        threshold: float = 0.7,
        limit: int = 10,
    ) -> list[RetrievedDocument]:
        """Pure vector-similarity search."""
        return await similarity_search(
            self.session,
            await self._embed_query(query),
            expected_dimensions=self._dimensions,
            filters=filters,
            threshold=threshold,
            limit=limit,
        )

    async def hybrid(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[RetrievedDocument]:
        """
        Hybrid retrieval: semantic results at 2x candidate depth merged
        with keyword matches, semantic hits preferred on id collisions,
        ranked by score descending.
        """
        embedding = await self._embed_query(query)

        semantic = await similarity_search(
            self.session,
            embedding,
            expected_dimensions=self._dimensions,
            filters=filters,
            threshold=threshold,
            limit=limit * 2,
        )
        keyword = await keyword_search(
            self.session, query, filters=filters, limit=limit
        )

        merged = merge_results(semantic, keyword, prefer_earlier=True)
        return rank_results(merged, limit)


def build_filters(
    entity_types: list[str] | None = None,
    company_ref: dict[str, str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    **extra_metadata: Any,
) -> RetrievalFilters:
    """
    Convenience constructor for common filter shapes. ``company_ref`` maps
    metadata keys to values (e.g. {"company_id": "123"}); additional
    keyword args become extra equality constraints or numeric minimums via
    the ``<field>__min`` convention.
    """
    equals: dict[str, str] = {k: str(v) for k, v in (company_ref or {}).items()}
    mins: dict[str, float] = {}
    for key, value in extra_metadata.items():
        if key.endswith("__min"):
            mins[key[: -len("__min")]] = float(value)
        else:
            equals[key] = str(value)
    return RetrievalFilters(
        entity_types=list(entity_types or []),
        metadata_equals=equals,
        metadata_min=mins,
        date_from=date_from,
        date_to=date_to,
    )