"""
News ingestion (Section 24).

Pipeline:

    News Provider → Deduplication → Content Extraction → Entity Resolution
    → Company Matching → Event Classification → Sentiment → Impact Score
    → Embedding → PostgreSQL
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.models.raw import RawNews
from app.domains.stock.normalization.companies import (
    EntityResolver,
    normalize_company_name,
)
from app.domains.stock.providers import MassiveProvider, NewsProvider, ProviderError
from app.domains.stock.scoring.sentiment import SentimentAnalyzer
from app.domains.stock.validation.duplicates import compute_news_hash
from app.domains.stock.validation.schema import validate_news


logger = get_logger(__name__)


class NewsIngestion:
    """Ingest news from providers, deduplicate, and link to companies."""

    def __init__(
        self,
        session: AsyncSession,
        provider: NewsProvider | None = None,
    ):
        self.session = session
        self.provider = provider or MassiveProvider()
        self._resolver = EntityResolver(session)
        self._sentiment = SentimentAnalyzer()

    async def _store_raw(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Store raw provider news payload."""

        raw = RawNews(
            provider=self.provider.provider_name,
            endpoint="/news",
            retrieved_at=datetime.now(timezone.utc),
            payload=payload,
        )

        self.session.add(raw)

    async def _resolve_companies(
        self,
        tickers: list[str],
        title: str | None = None,
        content: str | None = None,
    ) -> list[tuple[Company, str, float]]:
        """
        Resolve ticker symbols and company names to company records.

        Matching strategy:

        1. Direct ticker match.
        2. Company name match in title/content.

        Returns:
            List of (company, extraction_method, relevance_score).
        """

        results: list[tuple[Company, str, float]] = []
        seen_ids: set[int] = set()

        # ---------------------------------------------------------
        # 1. Ticker-based matching
        # ---------------------------------------------------------

        for ticker in tickers:
            if not ticker:
                continue

            company = await self._resolver.resolve(ticker=ticker)

            if company and company.id not in seen_ids:
                results.append(
                    (company, "ticker", 1.0)
                )
                seen_ids.add(company.id)

        # ---------------------------------------------------------
        # 2. Name-based matching — TITLE ONLY, word-boundary.
        #
        # The previous full-content substring match linked any article
        # that merely mentioned a company in passing ("...partnering with
        # Google instead of Apple..."), polluting company news feeds and
        # cascading into event detection + sentiment scoring. A company
        # must be named in the headline to be considered "about" it.
        # ---------------------------------------------------------

        if title:
            result = await self.session.execute(
                select(Company)
            )
            all_companies = result.scalars().all()

            for company in all_companies:
                if company.id in seen_ids:
                    continue

                if not company.name:
                    continue

                normalized_name = normalize_company_name(
                    company.name
                )

                if (
                    normalized_name
                    and len(normalized_name) > 2
                    and re.search(rf"\b{re.escape(normalized_name)}\b", title, re.IGNORECASE)
                ):
                    results.append(
                        (
                            company,
                            "name_match",
                            0.85,
                        )
                    )
                    seen_ids.add(company.id)

        return results

    async def ingest_company_news(
        self,
        ticker: str,
        limit: int = 50,
    ) -> int:
        """Ingest news for a specific company."""

        try:
            news_items = await self.provider.get_company_news(
                ticker,
                limit,
            )

            return await self._store_news(news_items)

        except ProviderError as exc:
            await self.session.rollback()

            logger.error(
                "Failed to ingest news for %s: %s",
                ticker,
                exc,
            )

            raise

        except Exception as exc:
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting news for %s: %s",
                ticker,
                exc,
            )

            raise

    async def ingest_search_news(
        self,
        query: str,
        limit: int = 50,
    ) -> int:
        """Ingest news matching a search query."""

        try:
            news_items = await self.provider.search_news(
                query,
                limit,
            )

            return await self._store_news(news_items)

        except ProviderError as exc:
            await self.session.rollback()

            logger.error(
                "Failed to ingest news for query '%s': %s",
                query,
                exc,
            )

            raise

        except Exception as exc:
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting news for query '%s': %s",
                query,
                exc,
            )

            raise

    async def _find_existing_news(
        self,
        content_hash: str,
        source: str,
        external_id: str | None,
    ) -> News | None:
        """
        Find an existing News row using the same deduplication strategy
        as the database constraints.

        Priority:

        1. source + external_id
        2. content_hash
        """

        if external_id:
            result = await self.session.execute(
                select(News).where(
                    News.source == source,
                    News.external_id == external_id,
                )
            )

            existing = result.scalar_one_or_none()

            if existing is not None:
                return existing

        result = await self.session.execute(
            select(News).where(
                News.content_hash == content_hash,
            )
        )

        return result.scalar_one_or_none()

    async def _insert_news(
        self,
        *,
        external_id: str | None,
        source: str,
        title: str,
        url: str | None,
        published_dt: datetime,
        summary: str | None,
        content: str | None,
        content_hash: str,
        sentiment: float | None,
    ) -> tuple[News | None, bool]:
        """
        Insert a News row safely.

        Returns:
            (news, inserted)

        Uses ON CONFLICT DO NOTHING because the database has:

            UNIQUE(content_hash)
            UNIQUE(source, external_id)
        """

        insert_stmt = (
            insert(News)
            .values(
                external_id=external_id,
                source=source,
                title=title,
                url=url,
                published_at=published_dt,
                summary=summary,
                content=content,
                language="en",
                content_hash=content_hash,
                sentiment=sentiment,
            )
            .returning(News.id)
            .on_conflict_do_nothing()
        )

        result = await self.session.execute(insert_stmt)
        row = result.first()

        if row is not None:
            inserted_news = await self.session.get(
                News,
                row[0],
            )

            if inserted_news is None:
                logger.warning(
                    "Inserted news row %s could not be loaded",
                    row[0],
                )
                return None, False

            return inserted_news, True

        existing_news = await self._find_existing_news(
            content_hash=content_hash,
            source=source,
            external_id=external_id,
        )

        if existing_news is None:
            logger.warning(
                "News conflict occurred but existing row could not "
                "be resolved: source=%s external_id=%s hash=%s",
                source,
                external_id,
                content_hash,
            )

        return existing_news, False

    async def _store_one_news(
        self,
        item: dict[str, Any],
    ) -> tuple[News | None, bool]:
        """
        Process and store one news item.

        This method intentionally does not commit or rollback.
        The caller owns the transaction boundary.
        """

        title = item.get("title", "")
        url = item.get("url")
        published_at = item.get("published_at")
        external_id = item.get("external_id")

        source_name = item.get(
            "source",
            self.provider.provider_name,
        )

        # ---------------------------------------------------------
        # Normalize timestamp for hashing
        # ---------------------------------------------------------

        published_iso = (
            published_at.isoformat()
            if hasattr(published_at, "isoformat")
            else str(published_at)
        )

        content_hash = compute_news_hash(
            title,
            url=url,
            published_at=published_iso,
            external_id=external_id,
            source=source_name,
        )

        # ---------------------------------------------------------
        # Parse published_at
        # ---------------------------------------------------------

        if isinstance(published_at, (int, float)):
            published_dt = datetime.fromtimestamp(
                (
                    published_at / 1000
                    if published_at > 1e12
                    else published_at
                ),
                tz=timezone.utc,
            )

        elif isinstance(published_at, str):
            published_dt = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )

            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(
                    tzinfo=timezone.utc
                )

        elif isinstance(published_at, datetime):
            published_dt = published_at

            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(
                    tzinfo=timezone.utc
                )

        else:
            published_dt = datetime.now(timezone.utc)

        # ---------------------------------------------------------
        # Validate
        # ---------------------------------------------------------

        validation_data = {
            "title": title,
            "source": source_name,
            "published_at": published_dt,
            "url": url,
            "content_hash": content_hash,
            "sentiment": item.get("sentiment"),
        }

        validation_result = validate_news(validation_data)

        if not validation_result:
            logger.warning(
                "Skipping invalid news item: %s",
                validation_result.errors,
            )
            return None, False

        # ---------------------------------------------------------
        # Insert safely
        # ---------------------------------------------------------

        inserted_news, was_inserted = await self._insert_news(
            external_id=external_id,
            source=source_name,
            title=title,
            url=url,
            published_dt=published_dt,
            summary=item.get("summary"),
            content=item.get("content"),
            content_hash=content_hash,
            sentiment=item.get("sentiment"),
        )

        if inserted_news is None:
            return None, False

        # ---------------------------------------------------------
        # Resolve companies
        # ---------------------------------------------------------

        tickers = item.get("tickers", [])

        companies = await self._resolve_companies(
            tickers,
            title=title,
            content=item.get("content"),
        )

        # ---------------------------------------------------------
        # Link news to companies
        # ---------------------------------------------------------

        for company, extraction_method, relevance in companies:
            exists_result = await self.session.execute(
                select(CompanyNews).where(
                    CompanyNews.company_id == company.id,
                    CompanyNews.news_id == inserted_news.id,
                )
            )

            if exists_result.scalar_one_or_none():
                continue

            company_news = CompanyNews(
                company_id=company.id,
                news_id=inserted_news.id,
                relevance_score=relevance,
                extraction_method=extraction_method,
            )

            self.session.add(company_news)

        return inserted_news, was_inserted

    async def _store_news(
        self,
        news_items: list[dict[str, Any]],
    ) -> int:
        """
        Store news items with deduplication and company linking.

        Each article uses a SAVEPOINT so a failure in one article does not
        roll back successfully processed articles from the same batch.
        """

        count = 0

        for item in news_items:
            try:
                # SAVEPOINT instead of full transaction rollback.
                #
                # This is critical: a normal session.rollback() here would
                # undo successful work from earlier articles in this batch.
                async with self.session.begin_nested():
                    _, was_inserted = await self._store_one_news(item)

                if was_inserted:
                    count += 1

            except Exception as exc:
                logger.exception(
                    "Failed to store news item '%s': %s",
                    item.get("title", "")[:100],
                    exc,
                )

                # begin_nested() rolls back only this article's SAVEPOINT.
                # Continue processing the remaining provider items.
                continue

        # Commit all successfully processed items.
        try:
            await self.session.commit()

        except Exception as exc:
            await self.session.rollback()

            logger.exception(
                "Failed to commit news batch: %s",
                exc,
            )

            raise

        logger.info(
            "Ingested %d news items (after dedup)",
            count,
        )

        return count