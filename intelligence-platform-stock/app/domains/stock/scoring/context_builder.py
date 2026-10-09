"""
Context builder for LLM research (Section 29).

The LLM should receive a structured context:
    Market Snapshot + Technical Snapshot + Fundamental Snapshot
    + Macro Snapshot + News Snapshot + Event Snapshot
    + Historical Similar Events → Context Builder → LLM
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.scoring.rag import RAGService
from app.domains.stock.snapshots import StockSnapshotReader

logger = get_logger(__name__)


class ContextBuilder(StockSnapshotReader):
    """
    Builds structured context for the LLM research analyst.

    Section 29: The LLM should receive a structured context, not raw data.
    """

    def __init__(self, session: AsyncSession, rag_service: RAGService | None = None):
        super().__init__(session)
        self.rag = rag_service or RAGService(session)

    async def build_full_context(
        self,
        company: Company,
        include_news: bool = True,
        include_fundamentals: bool = True,
        include_technical: bool = True,
        include_macro: bool = True,
    ) -> dict[str, Any]:
        """
        Build the complete structured context for LLM analysis.

        Section 29:
            Market Snapshot + Technical Snapshot + Fundamental Snapshot
            + Macro Snapshot + News Snapshot + Event Snapshot
            + Historical Similar Events
        """
        context: dict[str, Any] = {
            "company": {
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "industry": company.industry,
                "market_cap": company.market_cap,
            },
        }

        # Market snapshot
        context["market_snapshot"] = await self.build_market_snapshot(company.id)

        # Technical snapshot
        if include_technical:
            context["technical_snapshot"] = await self.build_technical_snapshot(company.id)
            context["anomaly_snapshot"] = await self.build_anomaly_snapshot(company.id)

        # Fundamental snapshot
        if include_fundamentals:
            context["fundamental_snapshot"] = await self.build_fundamental_snapshot(company.id)

        # News snapshot
        if include_news:
            context["news_snapshot"] = await self.build_news_snapshot(company.id)
            context["event_snapshot"] = await self.build_event_snapshot(company.id)

        # Macro snapshot
        if include_macro:
            context["macro_snapshot"] = await self.macro_engine.get_macro_snapshot()

        # Risk snapshot
        context["risk_snapshot"] = await self.build_risk_snapshot(company.id)

        # RAG: Historical similar events
        rag_context = await self.rag.retrieve_context(
            f"Analysis of {company.ticker} {company.name}",
            company_id=company.id,
        )
        context["rag_context"] = rag_context

        logger.info("Built full context for %s", company.ticker)
        return context