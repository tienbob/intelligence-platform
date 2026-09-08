"""
Analysis API endpoints (Section 46).

Asynchronous analysis:

    POST /analysis/company -> 202 Accepted (queued)

    GET  /analysis/{analysis_id} -> status / results

Integrity rules:

1. The deterministic InvestmentScore is authoritative for recommendation.
2. LLM recommendation text/details must never override the deterministic score.
3. Evidence confidence is based on actually resolved/valid evidence, not merely
   the presence of an evidence payload.
4. Missing/unavailable evidence is not automatically treated as contradictory.
5. Analysis execution is bound to the pre-created Analysis.company_id.
6. Confidence can never exceed the evidence integrity ceiling.
7. Source-backed claims expose their persisted identity where available.
8. Evidence without a real identity is not counted as resolved evidence.
9. An evidence ID alone never proves source identity or claim validity.
10. Recommendation confidence is also capped by evidence integrity.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import check_idempotency, store_idempotency_result
from app.domains.stock.models.analysis import (
    Analysis,
    AnalysisSource,
    InvestmentScore,
)
from app.domains.stock.models.company import Company
from app.domains.stock.schemas.analysis import (
    AnalysisCreateResponse,
    AnalysisRequest,
    AnalysisResponse,
    ConfidenceBreakdown,
    InvestmentRecommendation,
)
from app.domains.stock.services.company_analysis import execute_company_analysis
from app.shared.identity import (
    company_is_scoped,
    requester_scope,
    scoped_where,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# Confidence helpers
# ---------------------------------------------------------------------------


def _clamp_confidence(value: Any, default: Any = 0.0) -> Any:
    """Safely normalize a confidence value into [0, 1]."""
    if isinstance(value, bool):
        return default

    try:
        value = float(value)
    except (TypeError, ValueError):
        return default

    if value != value:  # NaN
        return default

    if value in (float("inf"), float("-inf")):
        return default

    return max(0.0, min(1.0, value))


def _score_value(value: Any, name: str, default: Any = None) -> Any:
    """
    Read a field from a deterministic score object OR a persisted score
    snapshot dict (``analysis.llm_analysis["_score_snapshot"]``).
    """
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _analysis_score_snapshot(analysis: Any) -> dict[str, Any] | None:
    """
    Return the deterministic score snapshot persisted WITH this analysis.

    Unlike the company's latest ``InvestmentScore`` row, this snapshot can
    never drift: it is the exact score the analysis was executed against.
    Returns ``None`` for legacy analyses persisted before the snapshot was
    introduced (the caller then falls back to the latest score row).
    """
    blob = (
        analysis.llm_analysis
        if isinstance(analysis.llm_analysis, dict)
        else {}
    )

    snapshot = blob.get("_score_snapshot")

    if isinstance(snapshot, dict) and snapshot.get("overall_score") is not None:
        return snapshot

    return None


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


_VALID_EVIDENCE_STATUSES = {
    "supported",
    "resolved",
    "valid",
}

_INVALID_EVIDENCE_STATUSES = {
    "invalid",
    "unsupported",
    "conflicting",
    "contradicted",
    "unavailable",
    "not_available",
    "not_retrievable",
    "unresolved",
    "error",
}


def _evidence_status(item: Any) -> str:
    """Return the normalized evidence resolution status."""
    if not isinstance(item, dict):
        return ""

    return str(
        item.get("status")
        or item.get("resolution_status")
        or item.get("validation_status")
        or ""
    ).strip().lower()


def _has_real_evidence_identity(item: Any) -> bool:
    """
    Determine whether an evidence record has a real persisted identity.

    A source name such as "SEC" or "Massive" is NOT sufficient.

    Valid identity should normally contain:

        entity_type + entity_id

    Critically, an arbitrary evidence ID such as "news_782" is only an
    identifier. It does not become valid evidence unless the resolver has
    already marked it as resolved/valid or the record contains sufficient
    persisted identity.
    """
    if not isinstance(item, dict):
        return False

    entity_type = item.get("entity_type")
    entity_id = item.get("entity_id")

    if entity_type is not None and entity_id is not None:
        return bool(
            str(entity_type).strip()
            and str(entity_id).strip()
        )

    # Do NOT treat source_id alone as resolved evidence.
    #
    # An ID such as:
    #
    #     news_782
    #
    # proves only that an identifier exists. It does not prove:
    #
    #     entity_type
    #     entity_id
    #     company
    #     provider
    #     metric
    #     period
    #     claim compatibility
    #
    # Those must come from the resolver.
    return False


def _is_valid_evidence_source(item: Any) -> bool:
    """
    Determine whether an evidence source is actually usable.

    Explicit resolver state is authoritative.

    Valid states:

        supported
        resolved
        valid

    Invalid states never count.

    For legacy records without explicit status, a real persisted identity is
    required.

    An evidence ID or source_id alone is NEVER sufficient.
    """
    if not isinstance(item, dict):
        return False

    status = _evidence_status(item)

    if status:
        return status in _VALID_EVIDENCE_STATUSES

    return _has_real_evidence_identity(item)


def _evidence_source_count(evidence: dict[str, Any]) -> int:
    """
    Count actually usable evidence sources.

    Never trust a declared source_count to manufacture evidence.
    """
    sources = evidence.get("sources")

    if not isinstance(sources, list):
        sources = evidence.get("evidence_sources")

    if not isinstance(sources, list):
        return 0

    return sum(
        1
        for source in sources
        if _is_valid_evidence_source(source)
    )


def _claim_status_counts(
    claim_validation: Any,
) -> tuple[int, int, int, int]:
    """
    Return:

        supported,
        unsupported,
        conflicting,
        unavailable

    Claim validation is intentionally tolerant of older payloads.
    """
    if not isinstance(claim_validation, list):
        return 0, 0, 0, 0

    supported = 0
    unsupported = 0
    conflicting = 0
    unavailable = 0

    for item in claim_validation:
        if not isinstance(item, dict):
            continue

        status = str(
            item.get("status")
            or item.get("resolution_status")
            or ""
        ).strip().lower()

        if status in _VALID_EVIDENCE_STATUSES:
            supported += 1

        elif status in {
            "unsupported",
            "unverified",
        }:
            unsupported += 1

        elif status in {
            "conflicting",
            "contradicted",
        }:
            conflicting += 1

        elif status in {
            "unavailable",
            "not_available",
            "not_retrievable",
        }:
            unavailable += 1

    return (
        supported,
        unsupported,
        conflicting,
        unavailable,
    )


def evidence_capped_confidence(
    *,
    data_conf: float,
    quant_conf: float,
    llm_conf: float,
    evidence_source_count: int,
    claims_unsupported: int,
    claims_conflicting: int = 0,
    claims_unavailable: int = 0,
    claims_supported: int = 0,
    invalid_source_count: int = 0,
) -> tuple[float, float]:
    """
    Compute:

        (evidence_confidence, overall_confidence)

    Evidence integrity is independent of LLM self-reported confidence.

    Rules:

        zero usable evidence
            -> maximum evidence confidence 0.50

        unsupported claim
            -> -0.10 each

        conflicting claim
            -> -0.20 each

        unavailable claim
            -> -0.05 each

        claims exist but none are supported
            -> maximum 0.50

    "Unavailable" is not equivalent to "false".
    """
    evidence_conf = 1.0

    if evidence_source_count <= 0:
        evidence_conf = min(
            evidence_conf,
            0.50,
        )

    if claims_unsupported > 0:
        evidence_conf = max(
            0.20,
            evidence_conf - 0.10 * claims_unsupported,
        )

    if claims_unavailable > 0:
        evidence_conf = max(
            0.20,
            evidence_conf - 0.05 * claims_unavailable,
        )

    if claims_conflicting > 0:
        evidence_conf = max(
            0.10,
            evidence_conf - 0.20 * claims_conflicting,
        )

    # Invalid sources (rejected by register_sources due to identity/type
    # mismatch) indicate evidence integrity issues. Each invalid source
    # reduces confidence because the pipeline could not reconcile the
    # retrieved record with its metadata.
    if invalid_source_count > 0:
        evidence_conf = max(
            0.15,
            evidence_conf - 0.07 * invalid_source_count,
        )

    total_claims = (
        claims_supported
        + claims_unsupported
        + claims_conflicting
        + claims_unavailable
    )

    if total_claims > 0 and claims_supported == 0:
        evidence_conf = min(
            evidence_conf,
            0.50,
        )

    data_conf = _clamp_confidence(
        data_conf,
        0.50,
    )

    quant_conf = _clamp_confidence(
        quant_conf,
        0.50,
    )

    llm_conf = _clamp_confidence(
        llm_conf,
        0.50,
    )

    overall = min(
        data_conf,
        quant_conf,
        llm_conf,
        evidence_conf,
    )

    return (
        round(evidence_conf, 4),
        round(overall, 4),
    )


# ---------------------------------------------------------------------------
# Evidence identity
# ---------------------------------------------------------------------------


def _source_identity(source: AnalysisSource) -> dict[str, Any]:
    """
    Build normalized persisted source identity.

    Only values that actually exist on the ORM object are emitted.
    """
    result: dict[str, Any] = {
        "type": getattr(source, "source_type", None),
        "source": getattr(source, "source_name", None),
        "metric": getattr(source, "metric", None),
        "value": getattr(source, "value", None),
        "period": getattr(source, "period", None),
    }

    optional_fields = (
        "entity_type",
        "entity_id",
        "company_id",
        "source_id",
        "provider",
        "status",
        "resolution_status",
        "canonical_metric",
        "canonical_value",
        "canonical_period",
        "location",
    )

    for field in optional_fields:
        if hasattr(source, field):
            value = getattr(source, field)

            if value is not None:
                result[field] = value

    return result


def _normalize_evidence_sources(
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return evidence sources as normalized dictionaries."""
    sources = evidence.get("sources")

    if not isinstance(sources, list):
        sources = evidence.get("evidence_sources")

    if not isinstance(sources, list):
        return []

    return [
        source
        for source in sources
        if isinstance(source, dict)
    ]


def _evidence_source_types(
    evidence: dict[str, Any],
    sources: list[dict[str, Any]],
) -> list[str]:
    """Return normalized unique evidence source types."""
    explicit = evidence.get("source_types")

    if isinstance(explicit, list):
        values = {
            str(value).strip()
            for value in explicit
            if value is not None
            and str(value).strip()
        }

        if values:
            return sorted(values)

    values: set[str] = set()

    for item in sources:
        source_type = (
            item.get("entity_type")
            or item.get("source_type")
            or item.get("type")
        )

        if source_type is None:
            continue

        value = str(source_type).strip()

        if value:
            values.add(value)

    return sorted(values)


def _invalid_evidence_sources(
    evidence_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Return invalid/unresolved evidence records for diagnostics.

    This intentionally preserves the resolver's failure reason where present.
    """
    invalid: list[dict[str, Any]] = []

    for source in evidence_sources:
        if _is_valid_evidence_source(source):
            continue

        item: dict[str, Any] = {}

        for field in (
            "evidence_id",
            "entity_type",
            "entity_id",
            "company_id",
            "source_id",
            "provider",
            "source_type",
            "source",
            "status",
            "resolution_status",
            "reason",
            "failure_reason",
        ):
            if field in source:
                item[field] = source[field]

        invalid.append(item)

    return invalid


# ---------------------------------------------------------------------------
# Analysis jobs
# ---------------------------------------------------------------------------


@router.get("/jobs")
async def list_analysis_jobs(
    request: Request,
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
):
    """List analysis jobs scoped to the requesting user's companies."""
    scope = await requester_scope(
        request,
        db,
    )

    query = (
        select(
            Analysis,
            Company.ticker,
        )
        .join(
            Company,
            Company.id == Analysis.company_id,
        )
    )

    query = scoped_where(
        query,
        Analysis.company_id,
        scope,
    )

    query = (
        query
        .order_by(Analysis.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    count_query = select(func.count(Analysis.id))

    count_query = scoped_where(
        count_query,
        Analysis.company_id,
        scope,
    )

    total = (
        await db.execute(count_query)
    ).scalar() or 0

    jobs: list[dict[str, Any]] = []

    for analysis, ticker in rows:
        jobs.append(
            {
                "id": analysis.id,
                "analysis_id": analysis.analysis_id,
                "ticker": ticker,
                "status": analysis.status,
                "investment_score": analysis.investment_score,
                "risk_score": analysis.risk_score,
                "confidence_score": analysis.confidence_score,
                "llm_model": analysis.llm_model,
                "llm_tokens_used": analysis.llm_tokens_used,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at
                    else None
                ),
            }
        )

    return {
        "jobs": jobs,
        "total": total,
    }


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------


class _AnalysisCancelled(Exception):
    """Internal sentinel used to stop analysis after cancellation."""


async def run_company_analysis(
    analysis_id: str,
    ticker: str,
    include_news: bool,
    include_fundamentals: bool,
    include_technical: bool,
    include_macro: bool,
):
    """
    Background task for POST /analysis/company.

    Analysis.company_id is authoritative.

    The supplied ticker is retained only for compatibility/context and is
    never used to bind the analysis to a different company.

    The include_* arguments are retained for API/background-task compatibility.
    Gate 6 moved orchestration into the framework pipeline, whose configuration
    is currently owned by build_stock_pipeline()/IntelligencePipeline.

    IMPORTANT:
    Do not forward include_* to execute_company_analysis(), because that
    function intentionally has no such parameters.
    """
    # Explicitly acknowledge compatibility arguments so they are not mistaken
    # for executor configuration.
    _ = (
        include_news,
        include_fundamentals,
        include_technical,
        include_macro,
    )

    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        analysis: Analysis | None = None

        try:
            result = await session.execute(
                select(Analysis).where(
                    Analysis.analysis_id == analysis_id
                )
            )

            analysis = result.scalar_one_or_none()

            if analysis is None:
                logger.error(
                    "Analysis %s disappeared before background execution",
                    analysis_id,
                )
                return

            if analysis.status == "cancelled":
                logger.info(
                    "Analysis %s was cancelled before execution",
                    analysis_id,
                )
                return

            company_result = await session.execute(
                select(Company).where(
                    Company.id == analysis.company_id
                )
            )

            company = company_result.scalar_one_or_none()

            if company is None:
                analysis.status = "failed"
                await session.commit()

                logger.error(
                    "Analysis %s references missing company_id=%s",
                    analysis_id,
                    analysis.company_id,
                )
                return

            if ticker and company.ticker.upper() != ticker.upper():
                logger.warning(
                    "Ticker mismatch for analysis %s: requested=%s bound=%s",
                    analysis_id,
                    ticker,
                    company.ticker,
                )

            analysis.status = "collecting_data"
            await session.commit()

            async def _stage(name: str) -> None:
                """
                Update stage while enforcing cancellation.

                A cancelled analysis must not continue silently through the
                pipeline.
                """
                result = await session.execute(
                    select(Analysis.status).where(
                        Analysis.id == analysis.id
                    )
                )

                current_status = result.scalar_one_or_none()

                if current_status == "cancelled":
                    raise _AnalysisCancelled(
                        f"Analysis {analysis_id} was cancelled"
                    )

                analysis.status = name
                await session.commit()

            # Gate 6:
            # execute_company_analysis() is the single production dispatch
            # point. Its public contract intentionally does NOT expose the
            # legacy include_* orchestration flags.
            await execute_company_analysis(
                session,
                company,
                existing=analysis,
                on_stage=_stage,
            )

        except _AnalysisCancelled:
            logger.info(
                "Analysis %s stopped after cancellation",
                analysis_id,
            )

            try:
                await session.rollback()

                result = await session.execute(
                    select(Analysis).where(
                        Analysis.analysis_id == analysis_id
                    )
                )

                cancelled_analysis = result.scalar_one_or_none()

                if (
                    cancelled_analysis is not None
                    and cancelled_analysis.status != "cancelled"
                ):
                    cancelled_analysis.status = "cancelled"
                    await session.commit()

            except Exception:
                logger.exception(
                    "Could not finalize cancellation for analysis %s",
                    analysis_id,
                )

        except Exception as exc:
            logger.exception(
                "Analysis %s failed: %s",
                analysis_id,
                exc,
            )

            try:
                await session.rollback()

                result = await session.execute(
                    select(Analysis).where(
                        Analysis.analysis_id == analysis_id
                    )
                )

                failed_analysis = result.scalar_one_or_none()

                if failed_analysis is not None:
                    if failed_analysis.status != "cancelled":
                        failed_analysis.status = "failed"
                        await session.commit()

            except Exception:
                logger.exception(
                    "Could not mark analysis %s as failed",
                    analysis_id,
                )


# ---------------------------------------------------------------------------
# Create analysis
# ---------------------------------------------------------------------------


@router.post(
    "/company",
    response_model=AnalysisCreateResponse,
    status_code=202,
)
async def create_company_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a company analysis job.

    Company access is verified before the job is created.
    """
    idempotency_key = await check_idempotency(
        fastapi_request
    )

    scope = await requester_scope(
        fastapi_request,
        db,
    )

    ticker = (
        request.ticker
        .upper()
        .strip()
    )

    if not ticker:
        raise HTTPException(
            status_code=422,
            detail="Ticker is required",
        )

    result = await db.execute(
        select(Company).where(
            Company.ticker == ticker
        )
    )

    company = result.scalar_one_or_none()

    # Auto-ingest is only permitted for unscoped callers.
    if not company:
        if scope is not None:
            raise HTTPException(
                status_code=404,
                detail=f"Company {ticker} not found",
            )

        from app.domains.stock.api.stocks import _auto_ingest_ticker

        company = await _auto_ingest_ticker(
            ticker,
            db,
        )

        if not company:
            raise HTTPException(
                status_code=404,
                detail=f"Company {ticker} not found",
            )

    if not company_is_scoped(
        company.id,
        scope,
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Company {ticker} not found",
        )

    analysis_id = str(uuid.uuid4())

    analysis = Analysis(
        analysis_id=analysis_id,
        company_id=company.id,
        analysis_type="company",
        analysis_version="1.0",
        status="queued",
    )

    db.add(analysis)
    await db.commit()

    background_tasks.add_task(
        run_company_analysis,
        analysis_id,
        ticker,
        request.include_news,
        request.include_fundamentals,
        request.include_technical,
        request.include_macro,
    )

    response = AnalysisCreateResponse(
        analysis_id=analysis_id,
        status="queued",
    )

    if idempotency_key:
        store_idempotency_result(
            idempotency_key,
            202,
            response.model_dump(),
        )

    return response


# ---------------------------------------------------------------------------
# Delete / cancel analysis
# ---------------------------------------------------------------------------


@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel or delete an analysis job.

    Active jobs are cancelled.

    Completed/failed/cancelled jobs are deleted.
    """
    result = await db.execute(
        select(Analysis).where(
            Analysis.analysis_id == analysis_id
        )
    )

    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    scope = await requester_scope(
        request,
        db,
    )

    if not company_is_scoped(
        analysis.company_id,
        scope,
    ):
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    active_statuses = {
        "queued",
        "collecting_data",
        "calculating_metrics",
        "retrieving_context",
        "llm_analysis",
        "risk_analysis",
    }

    if analysis.status in active_statuses:
        analysis.status = "cancelled"
        await db.commit()

        return {
            "analysis_id": analysis_id,
            "status": "cancelled",
            "message": "Analysis job cancelled",
        }

    await db.execute(
        delete(AnalysisSource).where(
            AnalysisSource.analysis_id == analysis.id
        )
    )

    await db.delete(analysis)
    await db.commit()

    return {
        "analysis_id": analysis_id,
        "status": "deleted",
        "message": "Analysis record deleted",
    }


# ---------------------------------------------------------------------------
# Get analysis
# ---------------------------------------------------------------------------


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResponse,
)
async def get_analysis(
    analysis_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get analysis status and results.

    The deterministic InvestmentScore is authoritative for recommendation.

    LLM-generated recommendation details are supplemental only.
    """
    result = await db.execute(
        select(Analysis).where(
            Analysis.analysis_id == analysis_id
        )
    )

    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    scope = await requester_scope(
        request,
        db,
    )

    if not company_is_scoped(
        analysis.company_id,
        scope,
    ):
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    # ------------------------------------------------------------------
    # Company
    # ------------------------------------------------------------------

    company_result = await db.execute(
        select(Company).where(
            Company.id == analysis.company_id
        )
    )

    company = company_result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Deterministic investment score
    # ------------------------------------------------------------------

    # The recommendation block must reflect the score THIS analysis was
    # executed against, not the company's latest InvestmentScore row.
    # A later recalculate_scores() run (daily worker) or another analysis
    # writes new rows; using the latest row here made the response drift:
    #   - recommendation.score  != investment_score
    #   - recommendation.risks  ("Risk score: 52")
    #     != risk_score          (48.38)
    #
    # The persisted _score_snapshot is authoritative. The latest row remains
    # only as a fallback for legacy analyses persisted before the snapshot
    # was introduced.
    score_result = await db.execute(
        select(InvestmentScore)
        .where(
            InvestmentScore.company_id == analysis.company_id
        )
        .order_by(
            InvestmentScore.timestamp.desc()
        )
        .limit(1)
    )

    latest_score = score_result.scalar_one_or_none()

    score_snapshot = _analysis_score_snapshot(analysis)

    score = (
        score_snapshot
        if score_snapshot is not None
        else latest_score
    )

    # ------------------------------------------------------------------
    # Persisted source-backed claims
    # ------------------------------------------------------------------

    claims_result = await db.execute(
        select(AnalysisSource)
        .where(
            AnalysisSource.analysis_id == analysis.id
        )
    )

    source_rows = claims_result.scalars().all()

    source_claims: list[dict[str, Any]] = []

    for source_row in source_rows:
        source_claims.append(
            {
                "claim": source_row.claim,
                "source": _source_identity(source_row),
            }
        )

    # ------------------------------------------------------------------
    # LLM payload
    # ------------------------------------------------------------------

    llm_payload = (
        analysis.llm_analysis
        if isinstance(analysis.llm_analysis, dict)
        else {}
    )

    # ------------------------------------------------------------------
    # Evidence payload
    # ------------------------------------------------------------------

    evidence = (
        llm_payload.get("_evidence")
        or llm_payload.get("evidence")
        or {}
    )

    if not isinstance(evidence, dict):
        evidence = {}

    evidence_sources = _normalize_evidence_sources(
        evidence
    )

    valid_evidence_source_count = _evidence_source_count(
        evidence
    )

    invalid_evidence_sources = _invalid_evidence_sources(
        evidence_sources
    )

    # ------------------------------------------------------------------
    # Claim validation
    # ------------------------------------------------------------------

    claim_validation = (
        llm_payload.get("claim_validation")
        or []
    )

    (
        claims_supported,
        claims_unsupported,
        claims_conflicting,
        claims_unavailable,
    ) = _claim_status_counts(
        claim_validation
    )

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    confidence_breakdown: ConfidenceBreakdown | None = None

    response_confidence = _clamp_confidence(
        analysis.confidence_score,
        0.0,
    )

    if score is not None:
        score_data_quality = _score_value(
            score,
            "data_quality_score",
        )
        data_conf = (
            score_data_quality
            if score_data_quality is not None
            else 0.5
        )

        score_confidence = _score_value(
            score,
            "confidence",
        )
        quant_conf = (
            score_confidence
            if score_confidence is not None
            else 0.5
        )

        llm_conf = llm_payload.get(
            "confidence",
            0.5,
        )

        llm_conf = _clamp_confidence(
            llm_conf,
            0.5,
        )

        evidence_conf, evidence_overall = (
            evidence_capped_confidence(
                data_conf=data_conf,
                quant_conf=quant_conf,
                llm_conf=llm_conf,
                evidence_source_count=valid_evidence_source_count,
                claims_unsupported=claims_unsupported,
                claims_conflicting=claims_conflicting,
                claims_unavailable=claims_unavailable,
                claims_supported=claims_supported,
                invalid_source_count=len(invalid_evidence_sources),
            )
        )

        deterministic_confidence = (
            analysis.confidence_score
            if analysis.confidence_score is not None
            else _score_value(score, "confidence")
        )

        if deterministic_confidence is not None:
            overall = min(
                _clamp_confidence(
                    deterministic_confidence,
                    0.0,
                ),
                evidence_overall,
            )
        else:
            overall = evidence_overall

        response_confidence = round(
            overall,
            4,
        )

        confidence_breakdown = ConfidenceBreakdown(
            data=round(
                _clamp_confidence(
                    data_conf,
                    0.5,
                ),
                4,
            ),
            quantitative=round(
                _clamp_confidence(
                    quant_conf,
                    0.5,
                ),
                4,
            ),
            llm=round(
                llm_conf,
                4,
            ),
            evidence=evidence_conf,
            overall=response_confidence,
        )

    # ------------------------------------------------------------------
    # Input context / snapshots
    # ------------------------------------------------------------------

    input_context = (
        llm_payload.get("_input_context", {})
    )

    if not isinstance(input_context, dict):
        input_context = {}

    rag_context = input_context.get(
        "rag_context",
        {},
    )

    if not isinstance(rag_context, dict):
        rag_context = {}

    snapshots = {
        "market": analysis.market_snapshot or {},
        "technical": analysis.technical_snapshot or {},
        "fundamental": analysis.fundamental_snapshot or {},
        "news": analysis.news_snapshot or {},
        "events": input_context.get(
            "event_snapshot",
            {},
        ),
        "macro": analysis.macro_snapshot or {},
        "risk": analysis.risk_snapshot or {},
    }

    # ------------------------------------------------------------------
    # Response evidence
    # ------------------------------------------------------------------

    response_evidence = {
        "source_count": valid_evidence_source_count,
        "source_types": _evidence_source_types(
            evidence,
            evidence_sources,
        ),
        "sources": evidence_sources,
        "invalid_sources": (
            evidence.get("invalid_sources")
            if isinstance(
                evidence.get("invalid_sources"),
                list,
            )
            else invalid_evidence_sources
        ),
        "valid_source_count": valid_evidence_source_count,
        "invalid_source_count": len(invalid_evidence_sources),
        "retrieval_stats": {
            "retrieved": (
                valid_evidence_source_count
                + len(invalid_evidence_sources)
            ),
            "valid": valid_evidence_source_count,
            "invalid": len(invalid_evidence_sources),
            "by_type": {
                key: len(items)
                for key, items in rag_context.items()
                if isinstance(items, list)
            },
        },
        "claim_counts": {
            "supported": claims_supported,
            "unsupported": claims_unsupported,
            "conflicting": claims_conflicting,
            "unavailable": claims_unavailable,
        },
    }

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    recommendation: InvestmentRecommendation | None = None

    if score is not None:
        """
        CRITICAL:

        The deterministic InvestmentScore is the source of truth.

        Never take recommendation from:

            llm_payload["recommendation"]
            llm_payload["recommendation_details"]

        Those values are supplemental only.
        """

        deterministic_recommendation = (
            _score_value(score, "recommendation")
            or "HOLD"
        )

        score_overall = _score_value(
            score,
            "overall_score",
        )
        deterministic_score = (
            score_overall
            if score_overall is not None
            else 0
        )

        score_confidence = _score_value(
            score,
            "confidence",
        )
        deterministic_score_confidence = (
            score_confidence
            if score_confidence is not None
            else 0
        )

        # --------------------------------------------------------------
        # Deterministic reasons
        # --------------------------------------------------------------

        reasons: list[str] = []

        fundamental_score = _score_value(
            score,
            "fundamental_score",
        )
        if fundamental_score is not None:
            reasons.append(
                f"Fundamental score: "
                f"{fundamental_score:.0f}"
            )

        valuation_score = _score_value(
            score,
            "valuation_score",
        )
        if valuation_score is not None:
            reasons.append(
                f"Valuation score: "
                f"{valuation_score:.0f}"
            )

        growth_score = _score_value(
            score,
            "growth_score",
        )
        if growth_score is not None:
            reasons.append(
                f"Growth score: "
                f"{growth_score:.0f}"
            )

        risks: list[str] = []

        risk_score = _score_value(
            score,
            "risk_score",
        )
        if risk_score is not None:
            risks.append(
                f"Risk score: "
                f"{risk_score:.0f}"
            )

        # --------------------------------------------------------------
        # Supplemental LLM recommendation details
        # --------------------------------------------------------------

        llm_recommendation = llm_payload.get(
            "recommendation_details"
        )

        if not isinstance(
            llm_recommendation,
            dict,
        ):
            llm_recommendation = {}

        invalidating_conditions = (
            llm_recommendation.get(
                "invalidating_conditions"
            )
        )

        if not isinstance(
            invalidating_conditions,
            list,
        ):
            invalidating_conditions = llm_payload.get(
                "invalidating_conditions",
                [],
            )

        if not isinstance(
            invalidating_conditions,
            list,
        ):
            invalidating_conditions = []

        recommended_weight = (
            llm_recommendation.get(
                "recommended_weight"
            )
        )

        # Recommendation confidence is capped by evidence integrity too.
        recommendation_confidence = min(
            _clamp_confidence(
                deterministic_score_confidence,
                0.0,
            ),
            response_confidence,
        )

        recommendation = InvestmentRecommendation(
            score=deterministic_score,
            confidence=round(
                recommendation_confidence,
                4,
            ),
            recommendation=deterministic_recommendation,
            reasons=reasons,
            risks=risks,
            invalidating_conditions=invalidating_conditions,
            recommended_weight=recommended_weight,
        )

    # ------------------------------------------------------------------
    # Sanitized analysis payload
    # ------------------------------------------------------------------

    # The persisted llm_analysis contains audit-only fields that duplicate
    # top-level response sections and bloat the payload.  Strip them from
    # the API response; the raw audit copy remains in the database.
    analysis_payload = (
        analysis.llm_analysis
        if isinstance(analysis.llm_analysis, dict)
        else {}
    )

    analysis_payload = {
        key: value
        for key, value in analysis_payload.items()
        if key not in {
            "_input_context",
            "_evidence",
            "_meta_full",
            "_score_snapshot",
            "source_backed_claims",
            "verified_source_backed_claims",
        }
    }

    # The LLM's self-reported confidence is informational only; the
    # authoritative reconciled confidence is the top-level `confidence` field.
    # Rewrite it here so consumers reading `analysis.confidence` see the same
    # value as the top-level response.
    if response_confidence is not None:
        analysis_payload["confidence"] = response_confidence

    # ------------------------------------------------------------------
    # Confidence provenance
    # ------------------------------------------------------------------

    confidence_provenance = {
        "authoritative": "response_confidence",
        "response_confidence": response_confidence,
        "deterministic_scoring_confidence": (
            _score_value(score, "confidence")
            if score is not None
            else None
        ),
        "llm_self_reported_confidence": (
            _clamp_confidence(llm_payload.get("confidence"), None)
        ),
        "evidence_integrity_confidence": evidence_conf,
        "risk_snapshot_confidence": (
            analysis.risk_snapshot.get("confidence")
            if isinstance(analysis.risk_snapshot, dict)
            else None
        ),
        "note": (
            "The top-level `confidence` and `confidence_breakdown.overall` "
            "values are authoritative. Other confidence values are inputs or "
            "auditable subcomponents."
        ),
    }

    # ------------------------------------------------------------------
    # Final response
    # ------------------------------------------------------------------

    return AnalysisResponse(
        analysis_id=analysis.analysis_id,
        status=analysis.status,
        ticker=(
            company.ticker
            if company
            else None
        ),
        investment_score=analysis.investment_score,
        risk_score=analysis.risk_score,
        confidence=response_confidence,
        confidence_breakdown=confidence_breakdown,
        confidence_provenance=confidence_provenance,
        source_backed_claims=source_claims,
        analysis=analysis_payload,
        snapshots=snapshots,
        rag_context=rag_context,
        evidence=response_evidence,
        recommendation=recommendation,
        created_at=(
            analysis.created_at.isoformat()
            if analysis.created_at
            else None
        ),
    )
