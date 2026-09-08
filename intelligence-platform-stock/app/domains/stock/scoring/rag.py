"""
RAG retrieval service (Section 27).

Architecture:

    User / Trigger
        -> Query Builder
        -> Vector Search / Keyword Search
        -> Metadata Filtering
        -> Identity Validation
        -> Relevant Documents
        -> Context Builder
        -> LLM

RAG retrieves from:

    News, SEC Filings, Company Events,
    Historical Events, Previous Analyses,
    Investment Theses

Important invariants:

1. company_id is a hard retrieval boundary whenever supplied.
2. Retrieved evidence identity is never rewritten by the caller.
3. Hybrid semantic and keyword searches use identical filters.
4. Retrieved metadata is validated before documents leave this service.
5. Missing identity metadata is not silently treated as valid company evidence.
6. Retrieval mode is preserved for downstream confidence/evidence accounting.
7. Canonical RetrievedDocument identity fields are authoritative.
8. Metadata is used for filtering/provenance, not for reconstructing identity.

Phase 4 (#157):

- Date range filtering
- Importance/materiality filtering
- Hybrid keyword search
- Event-type filtering
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models import Company
from app.domains.stock.scoring.embeddings import EmbeddingService
from app.intelligence.rag.ranking import merge_results, rank_results
from app.intelligence.rag.retrieval import keyword_search, similarity_search
from app.intelligence.rag.types import RetrievedDocument, RetrievalFilters


def _parse_rag_date(value: Any) -> datetime | None:
    """Parse a date value from RAG metadata into a timezone-aware datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue

    return None


logger = get_logger(__name__)


class RAGService:
    """
    Retrieval-Augmented Generation service.

    Uses pgvector for semantic similarity search with metadata filtering.

    Company identity is treated as a hard boundary. Retrieval results that
    cannot prove their company identity are rejected when company_id is
    supplied.

    Important:
        RetrievedDocument.entity_type and RetrievedDocument.entity_id are
        canonical identity fields. Metadata must never be used to rewrite
        or replace those values.
    """

    DEFAULT_SIMILARITY_THRESHOLD = 0.5
    MAX_LIMIT = 100

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService | None = None,
    ):
        self.session = session
        self.embedding_service = embedding_service or EmbeddingService()

    # ------------------------------------------------------------------
    # Core retrieval
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        company_id: int | None = None,
        entity_types: list[str] | None = None,
        limit: int = 10,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_importance: float | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant documents.

        Semantic retrieval is preferred. Keyword retrieval is used when:

        - embedding generation fails
        - vector retrieval fails
        - vector retrieval returns no candidates

        Both paths use the exact same filters.

        company_id is a hard retrieval boundary.

        Note:
            Keyword fallback searches the embeddings table, so it can recover
            keyword-relevant embedded documents but cannot recover source rows
            that have no embedding row.
        """
        query = self._normalize_query(query)

        if not query:
            return []

        limit = self._normalize_limit(limit)
        similarity_threshold = self._clamp_threshold(similarity_threshold)

        filters = self._build_filters(
            company_id=company_id,
            entity_types=entity_types,
            date_from=date_from,
            date_to=date_to,
            min_importance=min_importance,
            event_type=event_type,
        )

        # --------------------------------------------------------------
        # 1. Semantic retrieval
        # --------------------------------------------------------------

        semantic_failed = False

        try:
            query_embedding = await self.embedding_service.embed(query)

            documents = await similarity_search(
                self.session,
                query_embedding,
                expected_dimensions=self.embedding_service.dimensions,
                filters=filters,
                threshold=similarity_threshold,
                limit=limit,
            )

            documents = self._validate_documents(
                documents,
                company_id=company_id,
                expected_entity_types=entity_types,
            )

            if documents:
                return [
                    self._decorate_document(
                        doc,
                        retrieval_mode="semantic",
                    )
                    for doc in documents
                ]

            logger.info(
                "RAG semantic retrieval returned no documents; "
                "falling back to keyword retrieval. "
                "company_id=%s entity_types=%s threshold=%s",
                company_id,
                entity_types,
                similarity_threshold,
            )

        except Exception:
            semantic_failed = True

            logger.warning(
                "RAG semantic retrieval failed; falling back to keyword "
                "retrieval. company_id=%s entity_types=%s",
                company_id,
                entity_types,
                exc_info=True,
            )

        # --------------------------------------------------------------
        # 2. Keyword fallback
        # --------------------------------------------------------------

        try:
            keyword_docs = await keyword_search(
                self.session,
                query,
                filters=filters,
                limit=limit,
            )

            keyword_docs = self._validate_documents(
                keyword_docs,
                company_id=company_id,
                expected_entity_types=entity_types,
            )

            return [
                self._decorate_document(
                    doc,
                    retrieval_mode="keyword_fallback",
                )
                for doc in keyword_docs
            ]

        except Exception:
            logger.error(
                "RAG keyword fallback failed. "
                "company_id=%s entity_types=%s semantic_failed=%s",
                company_id,
                entity_types,
                semantic_failed,
                exc_info=True,
            )

            return []

    # ------------------------------------------------------------------
    # Hybrid retrieval
    # ------------------------------------------------------------------

    async def hybrid_search(
        self,
        query: str,
        company_id: int | None = None,
        entity_types: list[str] | None = None,
        limit: int = 10,
        similarity_threshold: float = 0.5,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_importance: float | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid retrieval:

            semantic/vector search
                    +
            keyword search
                    ->
            identity validation
                    ->
            deduplication
                    ->
            ranking

        Both retrieval paths use exactly the same filters.
        """
        query = self._normalize_query(query)

        if not query:
            return []

        limit = self._normalize_limit(limit)
        candidate_limit = min(max(limit * 2, limit), self.MAX_LIMIT)

        similarity_threshold = self._clamp_threshold(
            similarity_threshold
        )

        filters = self._build_filters(
            company_id=company_id,
            entity_types=entity_types,
            date_from=date_from,
            date_to=date_to,
            min_importance=min_importance,
            event_type=event_type,
        )

        # --------------------------------------------------------------
        # 1. Semantic candidates
        # --------------------------------------------------------------

        semantic_docs: list[RetrievedDocument] = []

        try:
            query_embedding = await self.embedding_service.embed(query)

            semantic_docs = await similarity_search(
                self.session,
                query_embedding,
                expected_dimensions=self.embedding_service.dimensions,
                filters=filters,
                threshold=similarity_threshold,
                limit=candidate_limit,
            )

            semantic_docs = self._validate_documents(
                semantic_docs,
                company_id=company_id,
                expected_entity_types=entity_types,
            )

        except Exception:
            logger.warning(
                "Hybrid semantic retrieval failed; continuing with "
                "keyword retrieval. company_id=%s",
                company_id,
                exc_info=True,
            )

        # --------------------------------------------------------------
        # 2. Keyword candidates
        # --------------------------------------------------------------

        keyword_docs: list[RetrievedDocument] = []

        try:
            keyword_docs = await keyword_search(
                self.session,
                query,
                filters=filters,
                limit=candidate_limit,
            )

            keyword_docs = self._validate_documents(
                keyword_docs,
                company_id=company_id,
                expected_entity_types=entity_types,
            )

        except Exception:
            logger.warning(
                "Hybrid keyword retrieval failed. company_id=%s",
                company_id,
                exc_info=True,
            )

        # --------------------------------------------------------------
        # 3. Mark retrieval provenance
        # --------------------------------------------------------------

        semantic_docs = [
            self._decorate_retrieved_document(
                doc,
                retrieval_mode="semantic",
            )
            for doc in semantic_docs
        ]

        keyword_docs = [
            self._decorate_retrieved_document(
                doc,
                retrieval_mode="keyword",
            )
            for doc in keyword_docs
        ]

        # --------------------------------------------------------------
        # 4. Merge and rank
        # --------------------------------------------------------------

        merged = merge_results(
            semantic_docs,
            keyword_docs,
            prefer_earlier=True,
        )

        ranked = rank_results(merged, limit)

        return [
            self._decorate_document(
                doc,
                retrieval_mode=self._get_retrieval_mode(doc),
            )
            for doc in ranked
        ]

    # ------------------------------------------------------------------
    # Specialized retrieval
    # ------------------------------------------------------------------

    async def retrieve_news(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 5,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_importance: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant company news."""
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["news"],
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            min_importance=min_importance,
            similarity_threshold=0.5,
        )

    async def retrieve_filings(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 3,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant SEC filings.

        Filing date bounds are supported because financial evidence must
        remain period-aware.
        """
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["sec_filing"],
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            similarity_threshold=0.5,
        )

    async def retrieve_events(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 5,
        event_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_importance: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant historical/company events."""
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["event"],
            limit=limit,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            min_importance=min_importance,
            similarity_threshold=0.5,
        )

    async def retrieve_similar_analyses(
        self,
        query: str,
        company_id: int | None = None,
        limit: int = 3,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve similar previous analyses."""
        return await self.retrieve(
            query,
            company_id=company_id,
            entity_types=["analysis"],
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            similarity_threshold=0.5,
        )

    # ------------------------------------------------------------------
    # Context retrieval
    # ------------------------------------------------------------------

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
        Retrieve complete RAG context for LLM analysis.

        Every bucket is company-scoped when company_id is supplied.

        Each entity type is retrieved independently so that one high-volume
        bucket cannot consume the entire context allocation.
        """
        query = self._normalize_query(query)

        if not query:
            return {}

        context: dict[str, list[dict[str, Any]]] = {}

        if include_news:
            if use_hybrid:
                context["news"] = await self.hybrid_search(
                    query,
                    company_id=company_id,
                    entity_types=["news"],
                    limit=5,
                    similarity_threshold=0.5,
                    date_from=date_from,
                    date_to=date_to,
                )
            else:
                context["news"] = await self.retrieve_news(
                    query,
                    company_id=company_id,
                    limit=5,
                    date_from=date_from,
                    date_to=date_to,
                )

        if include_filings:
            # Canonical entity_type key ("sec_filing") must match the
            # record's entity_type column and metadata in the embeddings
            # table. Using the plural collection name ("filings") made
            # register_sources() reject every filing as an
            # entity_type_mismatch, silently dropping SEC evidence.
            context["sec_filing"] = await self.retrieve_filings(
                query,
                company_id=company_id,
                limit=3,
                date_from=date_from,
                date_to=date_to,
            )

        if include_events:
            # Canonical entity_type key ("event") must match the record's
            # entity_type in the embeddings table. Using the plural
            # collection name ("events") caused register_sources() to reject
            # every event as an entity_type_mismatch.
            context["event"] = await self.retrieve_events(
                query,
                company_id=company_id,
                limit=5,
                date_from=date_from,
                date_to=date_to,
            )

        if include_analyses:
            # Same fix: use canonical "analysis" key, not "previous_analyses".
            context["analysis"] = (
                await self.retrieve_similar_analyses(
                    query,
                    company_id=company_id,
                    limit=3,
                    date_from=date_from,
                    date_to=date_to,
                )
            )

        logger.info(
            "RAG retrieved: %d news, %d filings, %d events, "
            "%d analyses company_id=%s",
            len(context.get("news", [])),
            len(context.get("sec_filing", [])),
            len(context.get("event", [])),
            len(context.get("analysis", [])),
            company_id,
        )

        return context

    async def retrieve_company_context(
        self,
        ticker: str,
        *,
        company_id: int,
        **kwargs: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Retrieve company context with mandatory identity scoping.

        The final identity filter is intentionally retained even though
        retrieval itself already applies company_id. This is defense in
        depth against malformed legacy metadata.

        Filings are scoped to the most recent reporting window (default two
        years) and returned newest-first so stale filings do not silently
        dominate the evidence set.
        """
        normalized_ticker = self._normalize_ticker(ticker)

        if not normalized_ticker or company_id is None:
            return {}

        # Default to the last two years for filings; financial evidence must
        # be period-relevant.  News/events may use the caller's window.
        filing_date_from = kwargs.pop("filing_date_from", None)
        filing_date_to = kwargs.pop("filing_date_to", None)

        if filing_date_from is None:
            from datetime import datetime, timedelta, timezone

            filing_date_from = datetime.now(timezone.utc) - timedelta(days=730)

        context = await self.retrieve_context(
            normalized_ticker,
            company_id=company_id,
            **kwargs,
        )

        filtered_context: dict[str, list[dict[str, Any]]] = {}

        for bucket, items in context.items():
            valid_items = []

            for item in items:
                if self._belongs_to_company(item, company_id):
                    valid_items.append(item)
                else:
                    logger.warning(
                        "Dropping RAG result with invalid company identity: "
                        "bucket=%s requested_company_id=%s metadata=%s",
                        bucket,
                        company_id,
                        item.get("metadata"),
                    )

            filtered_context[bucket] = valid_items

        # Re-fetch filings with a hard date window and newest-first ordering.
        # retrieve_context may return the oldest matches first when no date
        # ordering is applied; for filings we always want the latest period.
        # The canonical bucket key is "sec_filing" so register_sources()
        # accepts the evidence (metadata.entity_type is "sec_filing").
        filtered_context["sec_filing"] = await self.retrieve_filings(
            normalized_ticker,
            company_id=company_id,
            limit=3,
            date_from=filing_date_from,
            date_to=filing_date_to,
        )
        filtered_context["sec_filing"] = self._sort_by_date_descending(
            filtered_context["sec_filing"],
            date_fields=("published_at", "filed_date", "filing_date"),
        )

        return filtered_context

    @staticmethod
    def _sort_by_date_descending(
        items: list[dict[str, Any]],
        date_fields: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """Sort retrieval results by the first available date, newest first."""
        from datetime import datetime

        def _date_key(item: dict[str, Any]) -> datetime:
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}

            for field in date_fields:
                value = item.get(field) or metadata.get(field)
                if value is None:
                    continue
                parsed = _parse_rag_date(value)
                if parsed is not None:
                    return parsed

            # Items without a usable date sort to the bottom.
            return datetime.min

        return sorted(
            items,
            key=_date_key,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Ticker-specific retrieval
    # ------------------------------------------------------------------

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
        Retrieve by ticker using the database company identity.

        Ticker is resolved once to company_id and company_id becomes the
        actual retrieval boundary.

        Ticker-centric queries do NOT automatically receive an excessively
        high semantic threshold. Company identity is already enforced by
        the hard company_id filter.
        """
        normalized_ticker = self._normalize_ticker(ticker)

        if not normalized_ticker:
            return []

        company_id = await self._get_company_id_by_ticker(
            normalized_ticker
        )

        if company_id is None:
            logger.warning(
                "RAG ticker lookup failed: ticker=%s",
                normalized_ticker,
            )
            return []

        final_threshold = (
            self._clamp_threshold(similarity_threshold)
            if similarity_threshold is not None
            else self.DEFAULT_SIMILARITY_THRESHOLD
        )

        results = await self.retrieve(
            query=query,
            company_id=company_id,
            limit=limit,
            similarity_threshold=final_threshold,
            date_from=date_from,
            date_to=date_to,
        )

        # Do not rewrite source metadata. Only verify the requested
        # company identity.
        return [
            result
            for result in results
            if self._belongs_to_company(result, company_id)
        ]

    # ------------------------------------------------------------------
    # Filter construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filters(
        *,
        company_id: int | None,
        entity_types: list[str] | None,
        date_from: datetime | None,
        date_to: datetime | None,
        min_importance: float | None,
        event_type: str | None,
    ) -> RetrievalFilters:
        """
        Build one canonical filter object used by both vector and keyword
        retrieval.
        """
        metadata_equals: dict[str, str] = {}

        if company_id is not None:
            metadata_equals["company_id"] = str(company_id)

        if event_type is not None:
            normalized_event_type = str(event_type).strip()

            if normalized_event_type:
                metadata_equals["event_type"] = normalized_event_type

        metadata_min: dict[str, float] = {}

        if min_importance is not None:
            metadata_min["importance"] = float(
                max(0.0, min(1.0, float(min_importance)))
            )

        normalized_entity_types = [
            str(value).strip().lower()
            for value in (entity_types or [])
            if str(value).strip()
        ]

        # Preserve order while removing duplicates.
        normalized_entity_types = list(
            dict.fromkeys(normalized_entity_types)
        )

        return RetrievalFilters(
            entity_types=normalized_entity_types,
            metadata_equals=metadata_equals,
            metadata_min=metadata_min,
            date_from=date_from,
            date_to=date_to,
        )

    # ------------------------------------------------------------------
    # Identity validation
    # ------------------------------------------------------------------

    def _validate_documents(
        self,
        documents: list[RetrievedDocument],
        *,
        company_id: int | None,
        expected_entity_types: list[str] | None,
    ) -> list[RetrievedDocument]:
        """
        Validate retrieval identity before documents reach downstream
        analysis code.

        Canonical identity comes from RetrievedDocument itself:

            document.entity_type
            document.entity_id
            document.domain

        Metadata is only used for additional identity evidence such as
        company_id.

        This is deliberately stricter when company_id is supplied.
        """
        validated: list[RetrievedDocument] = []

        expected_types = {
            str(value).strip().lower()
            for value in (expected_entity_types or [])
            if str(value).strip()
        }

        for document in documents:
            if document is None:
                logger.warning(
                    "Dropping null RAG document."
                )
                continue

            # ----------------------------------------------------------
            # Canonical identity
            # ----------------------------------------------------------

            entity_type = self._normalize_entity_type(
                getattr(document, "entity_type", None)
            )

            entity_id = getattr(document, "entity_id", None)

            # Entity type must match the retrieval request.
            if expected_types and entity_type not in expected_types:
                logger.warning(
                    "Dropping RAG document due to entity_type mismatch: "
                    "expected=%s actual=%s entity_id=%s",
                    expected_types,
                    entity_type,
                    entity_id,
                )
                continue

            # Canonical entity identity is mandatory.
            if entity_id is None:
                logger.warning(
                    "Dropping RAG document without canonical entity_id: "
                    "entity_type=%s metadata=%s",
                    entity_type,
                    getattr(document, "metadata", None),
                )
                continue

            if not entity_type:
                logger.warning(
                    "Dropping RAG document without canonical entity_type: "
                    "entity_id=%s metadata=%s",
                    entity_id,
                    getattr(document, "metadata", None),
                )
                continue

            # ----------------------------------------------------------
            # Metadata validation
            # ----------------------------------------------------------

            metadata = dict(
                getattr(document, "metadata", {}) or {}
            )

            if not isinstance(metadata, dict):
                logger.warning(
                    "Dropping RAG document with invalid metadata type: "
                    "entity_type=%s entity_id=%s metadata_type=%s",
                    entity_type,
                    entity_id,
                    type(metadata).__name__,
                )
                continue

            # ----------------------------------------------------------
            # Company hard boundary
            # ----------------------------------------------------------

            if company_id is not None:
                record_company_id = metadata.get("company_id")

                if record_company_id is None:
                    logger.warning(
                        "Dropping RAG document without company identity: "
                        "requested_company_id=%s entity_type=%s "
                        "entity_id=%s",
                        company_id,
                        entity_type,
                        entity_id,
                    )
                    continue

                if str(record_company_id) != str(company_id):
                    logger.warning(
                        "Dropping cross-company RAG document: "
                        "requested_company_id=%s actual_company_id=%s "
                        "entity_type=%s entity_id=%s",
                        company_id,
                        record_company_id,
                        entity_type,
                        entity_id,
                    )
                    continue

            validated.append(document)

        return validated

    @staticmethod
    def _belongs_to_company(
        item: dict[str, Any],
        company_id: int,
    ) -> bool:
        """
        Defense-in-depth company identity check.

        Missing identity is invalid, not equivalent to unknown-but-valid.

        The company_id is intentionally read from metadata because company
        association is retrieval metadata, while entity_id/entity_type are
        canonical RetrievedDocument identity fields.
        """
        metadata = item.get("metadata") or {}

        if not isinstance(metadata, dict):
            return False

        record_company_id = metadata.get("company_id")

        if record_company_id is None:
            return False

        return str(record_company_id) == str(company_id)

    # ------------------------------------------------------------------
    # Retrieval metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _decorate_retrieved_document(
        document: RetrievedDocument,
        *,
        retrieval_mode: str,
    ) -> RetrievedDocument:
        """
        Attach retrieval metadata without changing evidence identity.
        """
        metadata = dict(
            getattr(document, "metadata", {}) or {}
        )

        metadata["retrieval_mode"] = retrieval_mode

        # Never modify:
        #   document.id
        #   document.domain
        #   document.entity_type
        #   document.entity_id

        document.metadata = metadata

        return document

    @staticmethod
    def _decorate_document(
        document: RetrievedDocument,
        *,
        retrieval_mode: str,
    ) -> dict[str, Any]:
        """
        Convert a RetrievedDocument to the legacy API shape while preserving
        provenance and canonical identity.
        """
        result = document.to_legacy_dict()

        metadata = dict(
            result.get("metadata") or {}
        )

        # Never manufacture or rewrite entity identity.
        metadata["retrieval_mode"] = (
            metadata.get("retrieval_mode") or retrieval_mode
        )

        result["metadata"] = metadata

        return result

    @staticmethod
    def _get_retrieval_mode(
        document: RetrievedDocument,
    ) -> str:
        """
        Return the retrieval mode stored on the document.

        This deliberately accepts one RetrievedDocument rather than
        *document so the object is not accidentally converted into a tuple.
        """
        metadata = getattr(document, "metadata", {}) or {}

        if not isinstance(metadata, dict):
            return "hybrid"

        return str(
            metadata.get("retrieval_mode") or "hybrid"
        )

    # ------------------------------------------------------------------
    # Ticker helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_dynamic_threshold(
        query: str,
        base_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> float:
        """
        Adjust similarity threshold based on query complexity.

        This intentionally does NOT raise the threshold simply because a
        query contains a ticker. Company identity is already enforced by
        company_id filtering.

        Complex queries can benefit from slightly wider recall.
        """
        base_threshold = RAGService._clamp_threshold(
            base_threshold
        )

        if len(query.split()) > 10:
            return max(base_threshold - 0.05, 0.4)

        return base_threshold

    @staticmethod
    def _is_ticker_centric_query(
        query: str,
    ) -> bool:
        """
        Detect explicit ticker-centric queries.

        Uses token boundaries instead of substring matching, avoiding cases
        such as NVDAILY accidentally matching NVDA.
        """
        normalized = query.upper()

        if re.search(r"\bTICKER\s*:", normalized):
            return True

        if re.search(r"\bTICKER\b", normalized):
            return True

        known_tickers = {
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "TSLA",
            "META",
            "NVDA",
            "JPM",
            "V",
            "WMT",
        }

        return any(
            re.search(
                rf"\b{re.escape(ticker)}\b",
                normalized,
            )
            for ticker in known_tickers
        )

    async def _get_company_id_by_ticker(
        self,
        ticker: str,
    ) -> int | None:
        """
        Resolve ticker to the canonical Company row.
        """
        result = await self.session.execute(
            select(Company.id).where(
                Company.ticker == ticker,
            )
        )

        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_query(
        query: str | None,
    ) -> str:
        if query is None:
            return ""

        return " ".join(
            str(query).strip().split()
        )

    @staticmethod
    def _normalize_ticker(
        ticker: str | None,
    ) -> str:
        if ticker is None:
            return ""

        return str(ticker).strip().upper()

    @staticmethod
    def _normalize_entity_type(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        return str(value).strip().lower()

    @staticmethod
    def _clamp_threshold(
        value: float,
    ) -> float:
        return max(
            0.0,
            min(1.0, float(value)),
        )

    @classmethod
    def _normalize_limit(
        cls,
        value: int,
    ) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 10

        return max(
            1,
            min(value, cls.MAX_LIMIT),
        )