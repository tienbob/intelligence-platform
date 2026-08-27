"""
Vector + keyword retrieval against the ``embeddings`` table.

Generic pgvector mechanics: cosine-distance search, query-embedding
preparation (codec-safe conversion and dimension validation), and
keyword ILIKE scoring with the legacy relevance formula. No domain
knowledge lives here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.intelligence.rag.filters import build_filter_sql
from app.intelligence.rag.types import RetrievedDocument, RetrievalFilters

logger = get_logger(__name__)


def prepare_query_embedding(
    embedding: Any,
    expected_dimensions: int,
) -> Any:
    """
    Convert a raw embedding to a pgvector ``Vector`` and validate its
    dimensionality. Raises ValueError on dimension mismatch so callers
    get a clear error instead of a Postgres "different vector dimensions"
    failure.
    """
    from pgvector.utils import Vector as PgVector

    if not isinstance(embedding, PgVector):
        embedding = PgVector(embedding)

    dims = (
        embedding.dimensions() if hasattr(embedding, "dimensions") else len(embedding)
    )
    if dims != expected_dimensions:
        raise ValueError(
            f"Query embedding has {dims} dimensions but the embeddings table "
            f"expects {expected_dimensions}. Check EMBEDDING_MODEL and "
            "EMBEDDING_DIMENSIONS consistency."
        )
    return embedding


async def similarity_search(
    session: AsyncSession,
    query_embedding: Any,
    *,
    expected_dimensions: int,
    filters: RetrievalFilters | None = None,
    threshold: float = 0.7,
    limit: int = 10,
) -> list[RetrievedDocument]:
    """
    Cosine-similarity vector search (pgvector `<=>` operator).

    Returns documents whose similarity is strictly greater than
    ``threshold``, ordered by similarity descending.
    """
    prepared = prepare_query_embedding(query_embedding, expected_dimensions)

    sql = """
        SELECT
            id, entity_type, entity_id, content, metadata,
            1 - (embedding <=> :embedding) as similarity
        FROM embeddings
        WHERE 1 - (embedding <=> :embedding) > :threshold
    """
    params: dict[str, Any] = {
        "embedding": prepared,
        "threshold": threshold,
    }

    filter_sql, filter_params = build_filter_sql(filters)
    sql += filter_sql
    params.update(filter_params)

    sql += " ORDER BY similarity DESC LIMIT :limit"
    params["limit"] = limit

    result = await session.execute(text(sql), params)
    return [
        RetrievedDocument(
            id=row.id,
            content=row.content or "",
            score=float(row.similarity),
            entity_type=row.entity_type or "",
            entity_id=row.entity_id,
            metadata=row.metadata or {},
        )
        for row in result.fetchall()
    ]


async def keyword_search(
    session: AsyncSession,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    limit: int = 10,
) -> list[RetrievedDocument]:
    """
    Keyword fallback search using ILIKE term matching.

    Relevance = min(matched_terms / max(sqrt(length(content), 1)) * 10, 0.7),
    so keyword hits never outrank strong semantic matches (>0.7).
    Queries with no usable terms (>2 chars) fall back to a single whole-query
    ILIKE scored at a flat 0.5.
    """
    query_terms = [t for t in query.lower().split() if len(t) > 2]
    if query_terms:
        term_conditions = " OR ".join(
            f"content ILIKE :kw_{i}" for i in range(len(query_terms))
        )
        sql = f"""
            SELECT
                id, entity_type, entity_id, content, metadata,
                LEAST(
                    ({" + ".join(f"CASE WHEN content ILIKE :kw_{i} THEN 1 ELSE 0 END" for i in range(len(query_terms)))})
                    * 1.0 / GREATEST(SQRT(LENGTH(content)), 1) * 10.0,
                    0.7
                ) as similarity
            FROM embeddings
            WHERE ({term_conditions})
        """
        params: dict[str, Any] = {
            f"kw_{i}": f"%{term}%" for i, term in enumerate(query_terms)
        }
    else:
        sql = """
            SELECT
                id, entity_type, entity_id, content, metadata,
                0.5 as similarity
            FROM embeddings
            WHERE content ILIKE :keyword
        """
        params = {"keyword": f"%{query}%"}

    filter_sql, filter_params = build_filter_sql(filters)
    sql += filter_sql
    params.update(filter_params)

    sql += " LIMIT :limit"
    params["limit"] = limit

    result = await session.execute(text(sql), params)
    return [
        RetrievedDocument(
            id=row.id,
            content=row.content or "",
            score=float(row.similarity),
            entity_type=row.entity_type or "",
            entity_id=row.entity_id,
            metadata=row.metadata or {},
        )
        for row in result.fetchall()
    ]