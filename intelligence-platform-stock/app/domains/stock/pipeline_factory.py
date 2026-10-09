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
    import app.domains.stock.normalization.companies  # noqa: F401
    from app.domains.stock.scoring.llm import LLMService as StockLLMService

    kwargs: dict[str, Any] = {
        "rag_service": StockRAGPipelineAdapter(),
        "llm_service": StockLLMService(),
        "validation_service": StockValidationAdapter(),
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
        from app.domains.stock.scoring.rag import RAGService as _StockRAGService

        ticker = kwargs.get("entity_id") or query
        async with async_session_factory() as session:
            rag = _StockRAGService(
                session, embedding_service=self._embedding_service
            )
            from app.domains.stock.normalization.companies import EntityResolver
            company = await EntityResolver(session).resolve(ticker=ticker)
            if company is None:
                raise LookupError(f"No Company record found for ticker {ticker}")
            return await rag.retrieve_context(
                f"Analysis of {company.ticker} {company.name}", company_id=company.id
            )


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


class StockValidationAdapter:
    """Apply Stock's output contract before generic result normalization."""

    async def validate(self, output, domain="stock", analysis_type="company"):
        from app.domains.stock.scoring.analysis_validator import AnalysisValidator
        from app.intelligence.validation import ValidationService
        if analysis_type == "company":
            AnalysisValidator.validate_company_analysis(output)
        return await ValidationService().validate(output, domain, analysis_type)
