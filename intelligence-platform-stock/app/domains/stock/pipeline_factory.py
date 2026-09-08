"""
Stock pipeline factory (Phase 10, §10.1).

The single canonical construction point for a fully-wired Stock analysis
pipeline. ``IntelligencePipeline`` itself stays completely domain-neutral;
only this factory knows how Stock's components are assembled.

    Tests            → IntelligencePipeline()          (minimal, fakes)
    Stock production → build_stock_pipeline()         (fully wired)
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.intelligence.pipeline import IntelligencePipeline

logger = get_logger(__name__)


def build_stock_pipeline(**overrides: Any) -> IntelligencePipeline:
    """
    Build the production Stock analysis pipeline.

    Wires Stock's RAG service (bucket semantics over the generic RAG core)
    and Stock's LLM service (investment prompts/validation/evidence over
    the generic LLM engine). Entity resolution, evidence, and validation
    use the framework defaults.

    Keyword overrides are passed straight through to the pipeline
    constructor (useful for tests / partial re-wiring).
    """
    from app.domains.stock.scoring.llm import LLMService as StockLLMService
    from app.domains.stock.scoring.rag import RAGService as StockRAGService

    kwargs: dict[str, Any] = {
        "rag_service": StockRAGPipelineAdapter(),
        "llm_service": StockLLMService(),
    }
    kwargs.update(overrides)

    logger.info(
        "Building Stock intelligence pipeline (rag=%s, llm=%s, overrides=%s)",
        type(kwargs["rag_service"]).__name__,
        type(kwargs["llm_service"]).__name__,
        sorted(overrides),
    )
    return IntelligencePipeline(**kwargs)


class StockRAGPipelineAdapter:
    """
    Bridges the pipeline's generic RAG interface to Stock's session-scoped
    ``RAGService``.

    The pipeline expects a stateless ``await rag.retrieve_context(query,
    domain=..., entity_type=..., entity_id=...)``; Stock's service binds an
    ``AsyncSession`` at construction and keys retrieval off the company
    ticker. This adapter opens a session per retrieval — no Stock classes
    are instantiated inside the framework pipeline itself.
    """

    def __init__(self, embedding_service: Any = None):
        self._embedding_service = embedding_service

    async def retrieve_context(self, query: str, **kwargs: Any) -> dict[str, Any]:
        import app.domains.stock.normalization.companies  # noqa: F401  (registers normalizer)
        from app.core.database import async_session_factory
        from app.domains.stock.models.company import Company
        from app.domains.stock.scoring.rag import RAGService as _StockRAGService
        from sqlalchemy import select

        ticker = kwargs.get("entity_id") or query
        empty = {"news": [], "sec_filing": [], "event": [], "analysis": []}
        try:
            async with async_session_factory() as session:
                company_result = await session.execute(
                    select(Company.id).where(Company.ticker == str(ticker).upper()).limit(1)
                )
                company_id = company_result.scalar_one_or_none()
                if company_id is None:
                    return empty
                rag = _StockRAGService(
                    session, embedding_service=self._embedding_service
                )
                return await rag.retrieve_company_context(ticker, company_id=company_id)
        except Exception:
            # Retrieval must never hard-fail an analysis: degrade to empty
            # buckets and let the stage diagnostics record the outage.
            logger.warning(
                "RAG retrieval failed for %s; degrading to empty buckets",
                ticker,
                exc_info=True,
            )
            return empty


async def run_stock_analysis(ticker: str, **overrides: Any):
    """
    Convenience: build the Stock pipeline and run a company analysis.

    This is the Phase 11 golden-equivalence entry point:

        production path → baseline_aapl.json
        run_stock_analysis("AAPL") → compare
    """
    from app.shared.entities import AnalysisRequest, EntityRef

    pipeline = build_stock_pipeline(**overrides)
    request = AnalysisRequest(
        entity_ref=EntityRef(domain="stock", entity_type="company", entity_id=ticker),
        analysis_type="company",
    )
    return await pipeline.run(request)
