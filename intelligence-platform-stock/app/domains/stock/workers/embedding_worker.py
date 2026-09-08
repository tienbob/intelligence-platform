"""
Embedding ingestion worker (Section 41).

Daily / periodic: Generate and persist RAG embeddings for news, events,
AI analyses, and SEC filings to support retrieval.
"""

from __future__ import annotations

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.scoring.embeddings import EmbeddingIngestionService

logger = get_logger(__name__)


async def ingest_rag_embeddings() -> None:
    """
    Embed and persist all currently unindexed Stock-domain RAG sources:

    - news
    - market events
    - AI analyses
    - SEC filing chunks
    """

    async with async_session_factory() as session:
        ingestion = EmbeddingIngestionService(session)

        try:
            counts = await ingestion.embed_all(limit=50)

            logger.info(
                (
                    "RAG embedding ingestion complete: "
                    "news=%d, events=%d, analyses=%d, filings=%d"
                ),
                counts.get("news", 0),
                counts.get("events", 0),
                counts.get("analyses", 0),
                counts.get("filings", 0),
            )

        except Exception as exc:
            # Reset the PostgreSQL transaction so the session is left clean.
            await session.rollback()

            logger.exception(
                "RAG embedding ingestion failed: %s",
                exc,
            )