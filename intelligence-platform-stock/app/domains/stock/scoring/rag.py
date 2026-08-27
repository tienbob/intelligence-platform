"""
RAG retrieval service (Section 27).

Architecture:
    User / Trigger → Query Builder → Vector Search → Metadata Filtering
    → Relevant Documents → Context Builder → LLM

RAG retrieves from:
    News, SEC Filings, Company Events, Historical Events,
    Previous Analyses, Investment Theses

Phase 4 (#157): Enhanced with:
- Date range filtering (Section 48)
- Importance/materiality filtering
- Hybrid keyword search (Section 47)
- Event-type filtering for event context
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.scoring.embeddings import EmbeddingService
from app.intelligence.rag.ranking import merge_results, rank_results
from app.intelligence.rag.retrieval import keyword_search, similarity_search
from app.intelligence.rag.types import RetrievedDocument, RetrievalFilters

logger = get_logger(__name__)
settings = get_stock_config()


class RAGService:
    """
    Retrieval-Augmented Generation service.

    Uses pgvector for semantic similarity search with metadata filtering.
    """

    def __init__(self, session: AsyncSession, embedding_service: EmbeddingService | None = None):
        self.session = session
        self.embedding_service = embedding_service or EmbeddingService()

    async def retrieve(
        self,
        query: str,
        company_id: int | None = None,
        entity_types: list[str] | None = None,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_importance: float | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant documents using vector similarity search.

        Phase 4: Enhanced metadata filtering (Section 48).

        Args:
            query: Natural language query
            company_id: Filter by company
            entity_types: Filter by entity types (news, sec_filing, event, etc.)
            limit: Max results
            similarity_threshold: Minimum cosine similarity
            date_from: Only include documents published after this date
            date_to: Only include documents published before this date
            min_importance: Minimum importance/materiality score (0..1)
            event_type: Filter events by type
        """
        # Generate query embedding
        query_embedding = await self.embedding_service.embed(query)

        # Generic retrieval core handles pgvector encoding, dimension
        # validation, filter SQL, thresholding, ordering, and limit.
        filters = RetrievalFilters(
            entity_types=list(entity_types or []),
            metadata_equals={
                **({"company_id": str(company_id)} if company_id is not None else {}),
                **({"event_type": event_type} if event_type is not None else {}),
            },
            metadata_min=(
                {"importance": float(min_importance)}
                if min_importance is not None
                else {}
            ),
            date_from=date_from,
            date_to=date_to,
        )

        documents = await similarity_search(
            self.session,
            query_embedding,
            expected_dimensions=self.embedding_service.dimensions,
            filters=filters,
            threshold=similarity_threshold,
            limit=limit,
        )
        return [doc.to_legacy_dict() for doc in documents]

    async def hybrid_search(
        self,
        query: str,
        company_id: int | None = None,
        entity_types: list[str] | None = None,
        limit: int = 10,
        similarity_threshold: float = 0.5,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid retrieval: vector similarity + keyword search (Section 47).

        Combines semantic search with full-text keyword matching,
        then merges and re-ranks results.
        """
        # 1. Semantic search (generic core, 2x candidate depth)
        semantic_results = await self.retrieve(
            query,
            company_id=company_id,
            entity_types=entity_types,
            limit=limit * 2,
            similarity_threshold=similarity_threshold,
            date_from=date_from,
            date_to=date_to,
        )

        # 2. Keyword search via the generic core (ILIKE relevance formula
        # with the legacy 0.7 cap and 0.5 fallback score).
        keyword_filters = RetrievalFilters(
            entity_types=list(entity_types or []),
            metadata_equals=(
                {"company_id": str(company_id)} if company_id is not None else {}
            ),
            date_from=date_from,
            date_to=date_to,
        )
        keyword_docs = await keyword_search(
            self.session, query, filters=keyword_filters, limit=limit
        )

        # 3. Merge + dedup by id preferring semantic hits (legacy behavior),
        # 4. then rank by similarity and return top results.
        merged = merge_results(
            [RetrievedDocument.from_legacy_dict(r) for r in semantic_results],
            keyword_docs,
            prefer_earlier=True,
        )
        ranked = rank_results(merged, limit)
        return [doc.to_legacy_dict() for doc in ranked]

    async def retrieve_news(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 5,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant news articles."""
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["news"],
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

    async def retrieve_filings(
        self, query: str, company_id: int | None = None, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Retrieve relevant SEC filings."""
        return await self.retrieve(
            query, company_id=company_id, entity_types=["sec_filing"], limit=limit
        )

    async def retrieve_events(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 5,
        event_type: str | None = None,
        date_from: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant historical events.

        Phase 4: Added event_type and date_from filters for event context.
        """
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["event"],
            limit=limit,
            event_type=event_type,
            date_from=date_from,
        )

    async def retrieve_similar_analyses(
        self, query: str, company_id: int | None = None, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Retrieve similar previous analyses."""
        return await self.retrieve(
            query, company_id=company_id, entity_types=["analysis"], limit=limit
        )

    async def retrieve_context(
        self,
        query: str,
        company_id: int | None = None,
        include_news: bool = True,
        include_filings: bool = True,
        include_events: bool = True,
        include_analyses: bool = True,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        use_hybrid: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Retrieve full RAG context for LLM analysis.

        Section 27: Retrieves from news, SEC filings, events, historical research.

        Phase 4: Added date range filtering and hybrid search option.
        """
        context: dict[str, list[dict[str, Any]]] = {}

        if include_news:
            if use_hybrid:
                context["news"] = await self.hybrid_search(
                    query,
                    company_id=company_id,
                    entity_types=["news"],
                    limit=5,
                    date_from=date_from,
                    date_to=date_to,
                )
            else:
                context["news"] = await self.retrieve_news(
                    query, company_id, date_from=date_from, date_to=date_to
                )
        if include_filings:
            context["filings"] = await self.retrieve_filings(query, company_id)
        if include_events:
            context["events"] = await self.retrieve_events(
                query, company_id, date_from=date_from
            )
        if include_analyses:
            context["previous_analyses"] = await self.retrieve_similar_analyses(query, company_id)

        logger.info(
            "RAG retrieved: %d news, %d filings, %d events, %d analyses",
            len(context.get("news", [])),
            len(context.get("filings", [])),
            len(context.get("events", [])),
            len(context.get("previous_analyses", [])),
        )
        return context

    # Ticker-specific retrieval methods
    async def retrieve_by_ticker(
        self,
        query: str,
        ticker: str,
        limit: int = 10,
        similarity_threshold: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Ticker-optimized retrieval with ticker-specific adjustments.

        Uses dynamic threshold calculation and ticker-specific metadata filtering.
        """
        # Normalize ticker (uppercase, strip whitespace)
        normalized_ticker = ticker.upper().strip()

        # Calculate dynamic threshold based on query characteristics
        final_threshold = self._calculate_dynamic_threshold(
            query, similarity_threshold or 0.7
        )

        # Get company_id from ticker
        company_id = await self._get_company_id_by_ticker(normalized_ticker)

        # Use standard retrieval with ticker-optimized parameters
        results = await self.retrieve(
            query=query,
            company_id=company_id,
            limit=limit,
            similarity_threshold=final_threshold,
            date_from=date_from,
            date_to=date_to,
        )

        # Apply ticker-specific post-processing
        return self._enhance_ticker_results(results, normalized_ticker)

    def _calculate_dynamic_threshold(
        self,
        query: str,
        base_threshold: float = 0.7
    ) -> float:
        """
        Adjust similarity threshold based on query analysis.

        Ticker queries typically need higher precision to avoid misleading results.
        """
        if self._is_ticker_centric_query(query):
            return max(base_threshold, 0.75)

        # For complex queries, use slightly lower threshold
        if len(query.split()) > 10:
            return max(base_threshold - 0.1, 0.5)

        return base_threshold

    def _is_ticker_centric_query(self, query: str) -> bool:
        """
        More robust ticker detection that avoids false positives.

        Checks for explicit ticker references and known financial tickers.
        """
        # Check for explicit ticker references
        if " ticker " in query.lower() or query.lower().startswith("ticker:"):
            return True

        # Check for known ticker patterns (symbols that are unlikely to be common words)
        # Use a curated list of ticker symbols that are less likely to be false positives
        financial_tickers = {"AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM", "V", "WMT"}
        query_upper = query.upper()
        return any(ticker in query_upper for ticker in financial_tickers)

    async def _get_company_id_by_ticker(self, ticker: str) -> int | None:
        """
        Get company_id from ticker symbol.

        Returns None if ticker not found.
        """
        from app.domains.stock.models import Company
        from sqlalchemy import select

        result = await self.session.execute(
            select(Company.id).where(Company.ticker == ticker)
        )
        company = result.scalar_one_or_none()
        return company.id if company else None

    def _enhance_ticker_results(
        self,
        results: list[dict[str, Any]],
        ticker: str
    ) -> list[dict[str, Any]]:
        """
        Enhance retrieval results with ticker-specific metadata and processing.
        """
        # Add ticker information to each result
        for result in results:
            metadata = result.get('metadata', {})
            metadata['ticker'] = ticker
            metadata['ticker_normalized'] = ticker.upper()
            result['metadata'] = metadata

        return results
