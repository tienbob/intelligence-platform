"""
Stock framework execution path (Phase 8, Step 8.3).

Runs a full company analysis **through the DomainModule contract and the
generic intelligence capabilities only** — no ``analysis_worker``
orchestration. This is the migration twin of the production path:

    production:  analysis_worker → engines → DB        (unchanged)
    framework:   run_framework_analysis() → this module  (new)

Both paths must produce structurally equivalent results for the same
ticker; the golden harness compares them.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.intelligence.entity_resolution import (
    get_entity_resolution_service,
)
from app.intelligence.registry import get_registry
from app.shared.entities import EntityRef

logger = get_logger(__name__)


async def resolve_entity(ticker: str) -> EntityRef:
    """
    Normalize a raw ticker through the generic entity-resolution service
    (Stock's normalizer is registered there at domain-import time).
    """
    import app.domains.stock.normalization.companies  # noqa: F401  (registers normalizer)

    svc = get_entity_resolution_service()
    raw_ref = EntityRef(domain="stock", entity_type="company", entity_id=ticker)
    resolved = await svc.resolve(raw_ref)
    if isinstance(resolved, EntityRef):
        return resolved
    return EntityRef(domain="stock", entity_type="company", entity_id=resolved)


async def retrieve_rag_context(entity_ref: EntityRef) -> dict[str, Any]:
    """Retrieve the Stock RAG context via the generic RAG core consumer."""
    from app.domains.stock.scoring.rag import RAGService

    rag = RAGService()
    return await rag.retrieve_context(str(entity_ref.entity_id))


async def analyze_llm(
    context_dict: dict[str, Any],
    *,
    evidence_attributor: Any = None,
) -> dict[str, Any]:
    """Run the Stock LLM analysis with validation + evidence attribution."""
    from app.domains.stock.scoring.analysis_validator import (
        AnalysisValidator,
        AnalysisValidationError,
    )
    from app.domains.stock.scoring.llm import LLMService

    llm = LLMService()
    system_prompt = llm.load_prompt("company_analysis")
    result = await llm.analyze(
        system_prompt,
        context_dict,
        user_query=None,
        evidence_attributor=evidence_attributor,
        analysis_type="company",
        prompt_name="company_analysis",
    )

    # Framework-agnostic validation of the structured output.
    try:
        AnalysisValidator.validate_company_analysis(result)
    except AnalysisValidationError:
        logger.exception("Framework-path LLM output failed validation")
        raise
    return result


async def run_framework_analysis(ticker: str) -> dict[str, Any]:
    """
    Execute a complete Stock analysis through the DomainModule contract.

    Stages (all capabilities come from either ``app.intelligence`` or the
    Stock manifest accessors — never from worker orchestration):

        1. Entity resolution      (generic service + Stock normalizer)
        2. RAG retrieval          (generic core via Stock bucket policy)
        3. Context construction   (manifest.get_context_builder)
        4. LLM analysis           (generic LLM engine + Stock prompts)
        5. Scoring                (manifest.get_scoring_strategy)

    Returns a structured dict suitable for golden comparison.
    """
    domain = get_registry().get("stock")
    if domain is None:
        raise RuntimeError("Stock domain not registered")

    # 1. Entity resolution
    entity_ref = await resolve_entity(ticker)

    # 2. RAG retrieval (bucket semantics live in Stock; mechanics in framework)
    rag_context = await retrieve_rag_context(entity_ref)

    # 3. Context construction via the manifest contract
    builder = domain.get_context_builder()
    context = await builder.build(
        entity_ref=entity_ref,
        evidence=[],
        observations=[],
        rag_context=rag_context,
    )

    # Flatten to the dict shape Stock's LLM consumes.
    context_dict = {
        "entity": context.entity,
        "rag_context": context.rag_context,
        **context.domain_snapshots,
    }

    # 4. LLM analysis (+ validation + evidence attribution inside)
    # Use the domain's factory so sources are registered from the RAG
    # context, same as the generic pipeline's §32 path.
    attributor = domain.get_evidence_attributor(context_dict)
    # Inject available source IDs into the context dict so the LLM
    # can cite them via `evidence_ids` in its structured output.
    context_dict["available_evidence_ids"] = sorted(
        attributor.source_registry.keys()
    )
    llm_output = await analyze_llm(context_dict, evidence_attributor=attributor)

    # 5. Domain scoring via the manifest contract
    strategy = domain.get_scoring_strategy()
    score_result = await strategy.score(entity_ref, context, llm_output)

    return {
        "entity": {
            "domain": entity_ref.domain,
            "entity_type": entity_ref.entity_type,
            "entity_id": entity_ref.entity_id,
        },
        "rag_counts": {
            bucket: len(items) for bucket, items in rag_context.items()
        },
        "evidence_source_count": len(
            llm_output.get("evidence", {}).get("evidence_sources", [])
        ),
        "llm_summary_present": bool(llm_output.get("summary")),
        "score": score_result.get("score"),
        "confidence": score_result.get("confidence"),
        "recommendation": score_result.get("recommendation"),
        "components": score_result.get("components", {}),
        "scoring_model": score_result.get("scoring_model"),
        "scoring_version": score_result.get("scoring_version"),
    }