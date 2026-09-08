"""
Vector + keyword retrieval against the ``embeddings`` table.

Generic pgvector mechanics: cosine-distance search, query-embedding
preparation (codec-safe conversion and dimension validation), and
keyword ILIKE scoring.

No domain knowledge lives here.

Domain-specific concerns such as:
- entity selection
- company/ticker filtering
- threshold policy
- freshness
- source quality
- relevance weighting
- result bucket allocation

belong in domain-layer orchestration.
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
    dimensionality.

    Raises:
        ValueError:
            If the embedding is missing, cannot be converted to pgvector,
            or has the wrong dimensionality.
    """
    from pgvector.utils import Vector as PgVector

    if embedding is None:
        raise ValueError("Query embedding cannot be None.")

    if expected_dimensions <= 0:
        raise ValueError(
            "Expected embedding dimensions must be greater than zero; "
            f"got {expected_dimensions!r}."
        )

    if not isinstance(embedding, PgVector):
        try:
            embedding = PgVector(embedding)
        except Exception as exc:
            raise ValueError(
                "Query embedding could not be converted to pgvector.Vector."
            ) from exc

    try:
        dims = embedding.dimensions()
    except Exception:
        try:
            dims = len(embedding)
        except Exception as exc:
            raise ValueError(
                "Unable to determine query embedding dimensionality."
            ) from exc

    if dims != expected_dimensions:
        raise ValueError(
            f"Query embedding has {dims} dimensions but the embeddings table "
            f"expects {expected_dimensions}. Check EMBEDDING_MODEL and "
            "EMBEDDING_DIMENSIONS consistency."
        )

    return embedding


def _validate_search_parameters(
    *,
    threshold: float,
    limit: int,
) -> None:
    """Validate common vector-search parameters."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            f"Similarity threshold must be between 0.0 and 1.0; "
            f"got {threshold!r}."
        )

    if limit <= 0:
        raise ValueError(
            f"Retrieval limit must be greater than zero; got {limit!r}."
        )


async def similarity_search(
    session: AsyncSession,
    query_embedding: Any,
    *,
    expected_dimensions: int,
    filters: RetrievalFilters | None = None,
    threshold: float = 0.5,
    limit: int = 10,
) -> list[RetrievedDocument]:
    """
    Perform cosine-similarity vector search using pgvector.

    Similarity is calculated as:

        1 - cosine_distance

    Rows are returned only when their similarity is strictly greater than
    ``threshold``.

    A moderate default threshold of 0.5 is used here because this framework
    cannot assume a universal threshold across embedding models or domains.
    Domain layers may provide stricter thresholds when appropriate.

    Rows with NULL embeddings are excluded.

    Args:
        session:
            Active SQLAlchemy async session.

        query_embedding:
            Raw embedding or pgvector Vector.

        expected_dimensions:
            Expected dimensionality of the embedding.

        filters:
            Generic retrieval filters.

        threshold:
            Minimum cosine similarity. Default: 0.5.

        limit:
            Maximum number of returned documents.

    Returns:
        Retrieved documents ordered by similarity descending.
    """
    _validate_search_parameters(
        threshold=threshold,
        limit=limit,
    )

    prepared = prepare_query_embedding(
        query_embedding,
        expected_dimensions,
    )

    sql = """
        SELECT
            id,
            domain,
            entity_type,
            entity_id,
            content,
            metadata,
            1 - (
                embedding <=> CAST(:embedding AS vector)
            ) AS similarity
        FROM embeddings
        WHERE embedding IS NOT NULL
          AND 1 - (
              embedding <=> CAST(:embedding AS vector)
          ) > :threshold
    """

    params: dict[str, Any] = {
        "embedding": prepared,
        "threshold": float(threshold),
    }

    filter_sql, filter_params = build_filter_sql(filters)

    sql += filter_sql
    params.update(filter_params)

    sql += """
        ORDER BY similarity DESC
        LIMIT :limit
    """

    params["limit"] = int(limit)

    try:
        result = await session.execute(
            text(sql),
            params,
        )
    except Exception:
        logger.exception(
            "Vector similarity search failed "
            "(threshold=%s, limit=%s).",
            threshold,
            limit,
        )
        raise

    rows = result.fetchall()

    return [
        RetrievedDocument(
            id=row.id,
            content=row.content or "",
            score=float(row.similarity),
            domain=row.domain or "",
            entity_type=row.entity_type or "",
            entity_id=row.entity_id,
            metadata=row.metadata or {},
        )
        for row in rows
    ]


async def keyword_search(
    session: AsyncSession,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    limit: int = 10,
) -> list[RetrievedDocument]:
    """
    Keyword fallback search using PostgreSQL ILIKE term matching.

    Terms shorter than three characters are ignored.

    For usable query terms, relevance is:

        matched_terms
        --------------------------- * 10
        sqrt(length(content))

    capped at 0.7.

    This prevents keyword matches from receiving a score above the
    semantic-search range while still allowing them to participate in
    hybrid retrieval.

    If no usable terms remain, the whole query is searched using ILIKE
    with a flat score of 0.5.

    Args:
        session:
            Active SQLAlchemy async session.

        query:
            Search query.

        filters:
            Generic retrieval filters.

        limit:
            Maximum number of returned documents.

    Returns:
        Retrieved documents.
    """
    if limit <= 0:
        raise ValueError(
            f"Retrieval limit must be greater than zero; got {limit!r}."
        )

    query = (query or "").strip()

    if not query:
        return []

    query_terms = [
        term
        for term in query.lower().split()
        if len(term) > 2
    ]

    if query_terms:
        term_conditions = " OR ".join(
            f"content ILIKE :kw_{i}"
            for i in range(len(query_terms))
        )

        matched_terms_expression = " + ".join(
            f"""
            CASE
                WHEN content ILIKE :kw_{i}
                THEN 1
                ELSE 0
            END
            """
            for i in range(len(query_terms))
        )

        sql = f"""
            SELECT
                id,
                domain,
                entity_type,
                entity_id,
                content,
                metadata,
                LEAST(
                    (
                        {matched_terms_expression}
                    ) * 1.0
                    / GREATEST(SQRT(LENGTH(content)), 1)
                    * 10.0,
                    0.7
                ) AS similarity
            FROM embeddings
            WHERE content IS NOT NULL
              AND ({term_conditions})
        """

        params: dict[str, Any] = {
            f"kw_{i}": f"%{term}%"
            for i, term in enumerate(query_terms)
        }

    else:
        sql = """
            SELECT
                id,
                domain,
                entity_type,
                entity_id,
                content,
                metadata,
                0.5 AS similarity
            FROM embeddings
            WHERE content IS NOT NULL
              AND content ILIKE :keyword
        """

        params = {
            "keyword": f"%{query}%",
        }

    filter_sql, filter_params = build_filter_sql(filters)

    sql += filter_sql
    params.update(filter_params)

    sql += """
        LIMIT :limit
    """

    params["limit"] = int(limit)

    try:
        result = await session.execute(
            text(sql),
            params,
        )
    except Exception:
        logger.exception(
            "Keyword retrieval failed (limit=%s).",
            limit,
        )
        raise

    rows = result.fetchall()

    return [
        RetrievedDocument(
            id=row.id,
            content=row.content or "",
            score=float(row.similarity),
            domain=row.domain or "",
            entity_type=row.entity_type or "",
            entity_id=row.entity_id,
            metadata=row.metadata or {},
        )
        for row in rows
    ]