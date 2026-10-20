"""
Embedding ingestion worker (Section 41).

Daily / periodic: Generate and persist RAG embeddings for news, events,
and AI analyses to support retrieval.
"""

from __future__ import annotations

import sqlalchemy

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.scoring.embeddings import EmbeddingIngestionService

logger = get_logger(__name__)


async def ingest_rag_embeddings() -> None:
    """Embed and persist all unindexed news, events, and analyses."""

    async with async_session_factory() as session:
        ingestion = EmbeddingIngestionService(session)

        try:
            counts = await ingestion.embed_all(limit=50)

            logger.info(
                "RAG embedding ingestion complete: news=%d, events=%d, analyses=%d",
                counts.get("news", 0),
                counts.get("events", 0),
                counts.get("analyses", 0),
            )

            # Cap-truncation warning: if any category exhausted the per-run
            # limit, the backlog is still growing and will silently lag
            # (improvement plan I5). One line here beats invisible staleness.
            capped = [kind for kind, n in counts.items() if n >= 50]
            if capped:
                logger.warning(
                    "Embedding backlog still truncated for: %s — consider "
                    "batching or raising the per-run limit",
                    ", ".join(sorted(capped)),
                )

        except sqlalchemy.exc.ProgrammingError:
            # Schema/code mismatch — never a data problem. Swallowing it
            # silently kills RAG embedding for every future run.
            logger.critical(
                "Programming error in RAG embedding ingestion — schema mismatch?",
            )
            raise
        except Exception as exc:
            # Reset the PostgreSQL transaction so the session is left clean.
            await session.rollback()

            logger.exception(
                "RAG embedding ingestion failed: %s",
                exc,
            )