"""
Stock embedding orchestration — WHAT gets embedded and WHEN.

The generic mechanics (provider client, batching, retries, pgvector
persistence, dedup filters) live in app.intelligence.embeddings/.

This module keeps only Stock domain knowledge:

    - which content becomes an embedding (news / events / analyses)
    - how content is extracted from each model
    - what metadata is attached (company_id, ticker, event_type, ...)
    - ticker mapping for company associations

Section 28. Uses pgvector for similarity search.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.analysis import Analysis
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.news import CompanyNews, News
from app.intelligence.embeddings import (
    Embedding,  # framework-owned ORM — consumed via contract, not defined here
    EmbeddingClient,
    GenericEmbeddingService,
    PgVectorStore,
    unembedded_filter,
)

logger = get_logger(__name__)


class EmbeddingService:
    """
    Generates embeddings for RAG retrieval.

    Thin domain facade over the generic embedding engine:
    provider interaction, batching, and vector persistence are
    delegated to app.intelligence.embeddings; this class adds
    Stock-specific semantics.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self._engine_client = EmbeddingClient(
            api_key=api_key,
            model=model,
        )

        self.api_key = self._engine_client.api_key
        self.model = self._engine_client.model
        self.dimensions = self._engine_client.dimensions

        self._generic = GenericEmbeddingService(
            client=self._engine_client,
        )

    # ------------------------------------------------------------------
    # Backward-compatible provider hooks
    # ------------------------------------------------------------------

    def _validate_config(
        self,
        require_api_key: bool = False,
    ) -> None:
        self._engine_client.validate_config(
            require_api_key=require_api_key,
        )

    async def _get_client(self) -> Any:
        return await self._engine_client._get_client()

    # ------------------------------------------------------------------
    # Embedding generation
    # ------------------------------------------------------------------

    async def embed(
        self,
        text: str,
    ) -> list[float]:
        """Generate an embedding for a single text."""
        return await self._engine_client.embed(text)

    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return await self._engine_client.embed_batch(texts)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def build_metadata(
        self,
        entity_type: str,
        entity_id: int,
        ticker: str | None = None,
        company_id: int | None = None,
        event_type: str | None = None,
        published_at: str | None = None,
        source: str | None = None,
        importance: float | None = None,
    ) -> dict[str, Any]:
        """
        Build metadata for an embedding.

        Supports hybrid retrieval:

            semantic similarity
            + company filter
            + date filter
            + event filter
            + importance
        """

        metadata: dict[str, Any] = {
            "domain": "stock",
            "entity_type": entity_type,
            "entity_id": entity_id,
        }

        if ticker:
            metadata["ticker"] = ticker

        if company_id is not None:
            metadata["company_id"] = company_id

        if event_type:
            metadata["event_type"] = event_type

        if published_at:
            metadata["published_at"] = published_at

        if source:
            metadata["source"] = source

        if importance is not None:
            metadata["importance"] = importance

        return metadata

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def store_embedding(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: int,
        content: str,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Embedding:
        """
        Persist an embedding row to the embeddings table.

        PgVectorStore owns vector encoding, dimension validation,
        persistence, and refresh behavior.
        """

        content = content.strip()

        if not content:
            raise ValueError(
                f"Cannot store empty embedding content for "
                f"{entity_type}:{entity_id}"
            )

        if embedding is None:
            embedding = await self.embed(content)

        from app.intelligence.embeddings.types import VectorRecord

        # ``PgVectorStore()`` resolves to the framework-owned Embedding ORM
        # (``app.intelligence.models.Embedding``) and to the platform
        # EMBEDDING_DIMENSIONS/EMBEDDING_MODEL settings — Stock consumes the
        # table through the framework contract instead of owning it.
        store = PgVectorStore()

        record = VectorRecord(
            domain="stock",
            entity_type=entity_type,
            entity_id=entity_id,
            content=content,
            vector=embedding,
            model=embedding_model or self.model,
            metadata=metadata or {},
        )

        return await store.store(
            session,
            record,
        )

    async def embed_and_store(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: int,
        content: str,
        embedding_model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Embedding:
        """Generate an embedding and persist it."""

        return await self.store_embedding(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            content=content,
            embedding_model=embedding_model,
            metadata=metadata,
        )


class EmbeddingIngestionService:
    """
    Ingests and persists RAG embeddings for Stock-domain data.

    Supported entities:

        news
        event
        analysis
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService | None = None,
    ):
        self.session = session
        self.embedding_service = (
            embedding_service or EmbeddingService()
        )

        # Lazily initialized because dimensions/model come from
        # the configured EmbeddingClient.
        self._generic: GenericEmbeddingService | None = None

    # ------------------------------------------------------------------
    # Generic embedding engine
    # ------------------------------------------------------------------

    def _generic_batch_service(self) -> GenericEmbeddingService:
        """
        Lazily bind the generic embedding engine to Stock's
        Embedding model / pgvector store.

        IMPORTANT:
        GenericEmbeddingService expects `store` to be callable:

            await self.store(session, record)

        PgVectorStore itself is an object, so we pass its `store`
        method rather than the PgVectorStore instance.
        """

        if self._generic is None:
            # Binds the generic engine to the framework-owned Embedding ORM
            # (PgVectorStore() resolves the model + dimensions centrally).
            pgvector_store = PgVectorStore()

            self._generic = GenericEmbeddingService(
                store=pgvector_store.store,
            )

        return self._generic

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    async def _select_unembedded(
        self,
        model: type,
        entity_type: str,
        limit: int,
    ) -> list[Any]:
        """
        Select source entities that do not yet have embeddings.

        Uses the generic correlated NOT EXISTS filter (scoped to
        domain="stock") so the same entity is not embedded repeatedly.
        """

        result = await self.session.execute(
            select(model)
            .where(
                unembedded_filter(
                    Embedding,
                    model,
                    entity_type,
                    domain="stock",
                )
            )
            .limit(limit)
        )

        return result.scalars().all()

    # ------------------------------------------------------------------
    # Company mapping
    # ------------------------------------------------------------------

    async def _ticker_map(
        self,
        company_ids: set[int],
    ) -> dict[int, str]:
        """Map company_id -> ticker."""

        if not company_ids:
            return {}

        result = await self.session.execute(
            select(
                Company.id,
                Company.ticker,
            ).where(
                Company.id.in_(company_ids)
            )
        )

        return {
            company_id: ticker
            for company_id, ticker in result.all()
        }

    # ------------------------------------------------------------------
    # Generic batch persistence
    # ------------------------------------------------------------------

    async def _embed_and_store_batch(
        self,
        items: list[
            tuple[
                str,
                int,
                str,
                dict[str, Any],
            ]
        ],
    ) -> int:
        """
        Embed and persist a batch of:

            (entity_type, entity_id, content, metadata)

        The generic embedding service handles batching, retries,
        and per-item failure isolation.
        """

        if not items:
            return 0

        from app.intelligence.embeddings.types import VectorRecord

        records = [
            VectorRecord(
                domain="stock",
                entity_type=entity_type,
                entity_id=entity_id,
                content=content,
                metadata=metadata,
            )
            for entity_type, entity_id, content, metadata in items
        ]

        service = self._generic_batch_service()

        return await service.embed_and_store_batch(
            self.session,
            records,
        )

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    async def embed_news(
        self,
        limit: int = 50,
    ) -> int:
        """Generate embeddings for unembedded news."""

        news_items = await self._select_unembedded(
            News,
            "news",
            limit,
        )

        if not news_items:
            return 0

        news_ids = [
            news.id
            for news in news_items
        ]

        # Preserve ALL company associations for each news item.
        rows = await self.session.execute(
            select(
                CompanyNews.news_id,
                CompanyNews.company_id,
                Company.ticker,
            )
            .join(
                Company,
                Company.id == CompanyNews.company_id,
            )
            .where(
                CompanyNews.news_id.in_(news_ids)
            )
            .order_by(
                CompanyNews.news_id
            )
        )

        news_companies: dict[
            int,
            list[tuple[int, str | None]],
        ] = {}

        for news_id, company_id, ticker in rows.all():
            news_companies.setdefault(
                news_id,
                [],
            ).append(
                (
                    company_id,
                    ticker,
                )
            )

        items: list[
            tuple[
                str,
                int,
                str,
                dict[str, Any],
            ]
        ] = []

        for news in news_items:
            content = (
                news.content
                or news.summary
                or news.title
                or ""
            ).strip()

            if not content:
                logger.debug(
                    "Skipping news %s because it has no content",
                    news.id,
                )
                continue

            companies = news_companies.get(
                news.id,
                [],
            )

            company_ids = [
                company_id
                for company_id, _ in companies
            ]

            tickers = [
                ticker
                for _, ticker in companies
                if ticker
            ]

            metadata = self.embedding_service.build_metadata(
                entity_type="news",
                entity_id=news.id,
                ticker=tickers[0] if tickers else None,
                company_id=(
                    company_ids[0]
                    if company_ids
                    else None
                ),
                source=news.source,
                published_at=(
                    news.published_at.isoformat()
                    if news.published_at
                    else None
                ),
            )

            # Preserve all company associations for multi-company news.
            if company_ids:
                metadata["company_ids"] = company_ids

            if tickers:
                metadata["tickers"] = tickers

            items.append(
                (
                    "news",
                    news.id,
                    content,
                    metadata,
                )
            )

        count = await self._embed_and_store_batch(
            items
        )

        logger.info(
            "Embedded %d news items",
            count,
        )

        return count

    # ------------------------------------------------------------------
    # Market events
    # ------------------------------------------------------------------

    async def embed_events(
        self,
        limit: int = 50,
    ) -> int:
        """Generate embeddings for unembedded market events."""

        events = await self._select_unembedded(
            MarketEvent,
            "event",
            limit,
        )

        if not events:
            return 0

        company_ids = {
            event.company_id
            for event in events
            if event.company_id is not None
        }

        ticker_map = await self._ticker_map(
            company_ids
        )

        items: list[
            tuple[
                str,
                int,
                str,
                dict[str, Any],
            ]
        ] = []

        for event in events:
            content = (
                f"{event.event_type}: "
                f"{event.description or ''}"
            ).strip()

            if not content:
                logger.debug(
                    "Skipping event %s because it has no content",
                    event.id,
                )
                continue

            ticker = (
                ticker_map.get(event.company_id)
                if event.company_id is not None
                else None
            )

            metadata = self.embedding_service.build_metadata(
                entity_type="event",
                entity_id=event.id,
                ticker=ticker,
                company_id=event.company_id,
                event_type=event.event_type,
                published_at=(
                    event.event_date.isoformat()
                    if event.event_date
                    else None
                ),
                source="market_event",
            )

            items.append(
                (
                    "event",
                    event.id,
                    content,
                    metadata,
                )
            )

        count = await self._embed_and_store_batch(
            items
        )

        logger.info(
            "Embedded %d market events",
            count,
        )

        return count

    # ------------------------------------------------------------------
    # AI analyses
    # ------------------------------------------------------------------

    async def embed_analyses(
        self,
        limit: int = 50,
    ) -> int:
        """Generate embeddings for unembedded AI analyses."""

        analyses = await self._select_unembedded(
            Analysis,
            "analysis",
            limit,
        )

        if not analyses:
            return 0

        company_ids = {
            analysis.company_id
            for analysis in analyses
            if analysis.company_id is not None
        }

        ticker_map = await self._ticker_map(
            company_ids
        )

        items: list[
            tuple[
                str,
                int,
                str,
                dict[str, Any],
            ]
        ] = []

        for analysis in analyses:
            if isinstance(
                analysis.llm_analysis,
                dict,
            ):
                content = (
                    analysis.llm_analysis.get("summary")
                    or json.dumps(
                        analysis.llm_analysis,
                        indent=2,
                        default=str,
                    )
                )
            else:
                content = str(
                    analysis.llm_analysis or ""
                )

            content = content.strip()

            if not content:
                logger.debug(
                    "Skipping analysis %s because it has no content",
                    analysis.id,
                )
                continue

            ticker = (
                ticker_map.get(analysis.company_id)
                if analysis.company_id is not None
                else None
            )

            metadata = self.embedding_service.build_metadata(
                entity_type="analysis",
                entity_id=analysis.id,
                ticker=ticker,
                company_id=analysis.company_id,
                source=analysis.analysis_type,
                importance=analysis.confidence_score,
            )

            items.append(
                (
                    "analysis",
                    analysis.id,
                    content,
                    metadata,
                )
            )

        count = await self._embed_and_store_batch(
            items
        )

        logger.info(
            "Embedded %d AI analyses",
            count,
        )

        return count

    # ------------------------------------------------------------------
    # All RAG sources
    # ------------------------------------------------------------------

    async def embed_all(
        self,
        limit: int = 50,
    ) -> dict[str, int]:
        """
        Embed and persist all currently unindexed:

            - news
            - market events
            - AI analyses
        """

        news_count = await self.embed_news(limit)
        event_count = await self.embed_events(limit)
        analysis_count = await self.embed_analyses(limit)

        counts = {
            "news": news_count,
            "events": event_count,
            "analyses": analysis_count,
        }

        logger.info(
            "Embedding ingestion complete: %s",
            counts,
        )

        return counts