"""Compatibility helpers for the canonical Stock intelligence pipeline.

Production dispatch, golden comparisons and this entry point all use
build_stock_pipeline(); there is no second framework orchestration path.
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
    """Use the same session-scoped, entity-filtered retrieval as production."""
    from app.domains.stock.pipeline_factory import StockRAGPipelineAdapter
    return await StockRAGPipelineAdapter().retrieve_context(entity_ref.entity_id, entity_id=entity_ref.entity_id)


async def run_framework_analysis(ticker: str) -> dict[str, Any]:
    """Compatibility entry point; all orchestration belongs to the canonical pipeline."""
    from app.domains.stock.pipeline_factory import run_stock_analysis
    result = await run_stock_analysis(ticker)
    if result.status != "completed":
        raise RuntimeError(f"Framework analysis failed: {result.metadata.get('stages', {})}")
    metadata = result.metadata
    score = metadata.get('scoring_metadata', {})
    llm = metadata.get('llm_output', {})
    return {
        'entity': {'domain': result.entity_ref.domain, 'entity_type': result.entity_ref.entity_type,
                   'entity_id': result.entity_ref.entity_id},
        'rag_counts': {bucket: len(items) for bucket, items in metadata.get('rag_context', {}).items()},
        'evidence_source_count': len(llm.get('evidence', {}).get('evidence_sources', [])),
        'llm_summary_present': bool(result.summary),
        'score': result.score, 'confidence': result.confidence,
        'recommendation': result.recommendation,
        'components': score.get('components', {}),
        'scoring_model': score.get('scoring_model'), 'scoring_version': score.get('scoring_version'),
    }
