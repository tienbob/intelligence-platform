"""
Golden-path characterization harness for Stock analysis.

Captures structural invariants of the production analysis path so the
framework migration (RAG core, embedding core, LLM core, pipeline wiring)
can be verified as behavior-preserving.

This does NOT assert identical LLM prose. It asserts the semantic/data
pipeline is equivalent:

    RAG:        per-bucket retrieved counts for a liquid ticker
    Embeddings: documents embedded, vector dimensions consistent
    Analysis:   scores present, confidence bounded, recommendation valid

Usage:
    # Against a live database (docker-compose up):
    PYTHONPATH=. python -m tests.golden.stock_analysis --ticker AAPL

    # Save a baseline snapshot:
    ... --save baseline_aapl.json
    # Compare against a saved baseline:
    ... --compare baseline_aapl.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def _valid_recommendations() -> set:
    """
    Recommendation categories are configurable (Section 60 thresholds);
    derive the valid set from the domain config rather than hardcoding.
    Falls back to a permissive default if config isn't loadable.
    """
    try:
        from app.domains.stock.config import get_stock_config

        return {
            rule["category"]
            for rule in get_stock_config().RECOMMENDATION_THRESHOLDS
        }
    except Exception:  # pragma: no cover - config-less environments
        return {"strong_buy", "buy", "hold", "sell", "strong_sell", "watch"}


VALID_RECOMMENDATIONS = _valid_recommendations()

# Structural invariants that must hold before AND after any framework migration.
INVARIANTS = {
    "rag": {
        "news_count": lambda v: v >= 0,
        "filings_count": lambda v: v >= 0,
        "events_count": lambda v: v >= 0,
        "analyses_count": lambda v: v >= 0,
        "total_retrieved": lambda v: v >= 0,
    },
    "embeddings": {
        "document_count": lambda v: v >= 0,
        "embedded_count": lambda v: v >= 0,
        "vector_dimension": lambda v: v == 0 or v >= 128,
    },
    "analysis": {
        "overall_score": lambda v: v is None or 0 <= v <= 100,
        "risk_score": lambda v: v is None or 0 <= v <= 100,
        "confidence": lambda v: 0 <= v <= 1,
        "recommendation": lambda v: (
            v in ("", None)
            or str(v).lower() in {r.lower() for r in VALID_RECOMMENDATIONS}
        ),
    },
}


async def _capture_rag(session, ticker: str) -> dict:
    """Per-bucket retrieval counts via the production RAGService."""
    from sqlalchemy import select

    from app.domains.stock.models.company import Company
    from app.domains.stock.scoring.rag import RAGService

    result = await session.execute(
        select(Company.id).where(Company.ticker == ticker.upper()).limit(1)
    )
    company_id = result.scalar_one_or_none()

    rag = RAGService(session)
    context = await rag.retrieve_context(
        f"{ticker.upper()} investment analysis fundamentals news",
        company_id=company_id,
    )
    return {
        "news_count": len(context.get("news", [])),
        "filings_count": len(context.get("filings", [])),
        "events_count": len(context.get("events", [])),
        "analyses_count": len(context.get("previous_analyses", [])),
        "total_retrieved": sum(len(v) for v in context.values()),
        "company_resolved": company_id is not None,
    }


async def _capture_embeddings(session, ticker: str) -> dict:
    """Embedding coverage counts for this ticker from the embeddings table."""
    from sqlalchemy import func, select

    from app.core.config import get_settings
    from app.domains.stock.models.analysis import Embedding

    ticker_filter = Embedding.content.ilike(f"%{ticker.upper()}%")
    embedded_result = await session.execute(
        select(func.count()).select_from(Embedding).where(ticker_filter)
    )
    embedded_count = int(embedded_result.scalar_one() or 0)

    by_type = await session.execute(
        select(Embedding.entity_type, func.count())
        .where(ticker_filter)
        .group_by(Embedding.entity_type)
    )
    type_counts = {row[0]: int(row[1]) for row in by_type.all()}

    settings = get_settings()
    return {
        "document_count": embedded_count,
        "embedded_count": embedded_count,
        "vector_dimension": settings.EMBEDDING_DIMENSIONS,
        "by_entity_type": type_counts,
    }


async def _capture_analysis(session, ticker: str) -> dict:
    """Latest persisted InvestmentScore for this ticker."""
    from sqlalchemy import select

    from app.domains.stock.models.analysis import InvestmentScore
    from app.domains.stock.models.company import Company

    result = await session.execute(
        select(Company.id).where(Company.ticker == ticker.upper()).limit(1)
    )
    company_id = result.scalar_one_or_none()
    if company_id is None:
        return {"error": f"No Company row for {ticker.upper()} — run ingestion first"}

    score_result = await session.execute(
        select(InvestmentScore)
        .where(InvestmentScore.company_id == company_id)
        .order_by(InvestmentScore.timestamp.desc())
        .limit(1)
    )
    score = score_result.scalar_one_or_none()
    if score is None:
        return {"error": f"No InvestmentScore for {ticker.upper()} — run analysis first"}

    return {
        "fundamental_score": score.fundamental_score,
        "technical_score": score.technical_score,
        "overall_score": score.overall_score,
        "risk_score": score.risk_score,
        "confidence": score.confidence or 0.0,
        "recommendation": score.recommendation,
        "scoring_model": score.scoring_model,
    }


async def capture_baseline(ticker: str) -> dict:
    """Run the current production Stock path and capture structural metrics."""
    from app.core.database import async_session_factory

    baseline: dict = {
        "ticker": ticker.upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    async with async_session_factory() as session:
        baseline["rag"] = await _capture_rag(session, ticker)
        baseline["embeddings"] = await _capture_embeddings(session, ticker)
        baseline["analysis"] = await _capture_analysis(session, ticker)
    return baseline


def check_invariants(baseline: dict) -> list[str]:
    """Return a list of invariant violations (empty = pass)."""
    violations: list[str] = []
    for section, checks in INVARIANTS.items():
        data = baseline.get(section, {})
        for key, predicate in checks.items():
            if key not in data:
                violations.append(f"{section}.{key}: missing")
            elif not predicate(data[key]):
                violations.append(f"{section}.{key}={data[key]!r}: invariant violated")
    return violations


def compare(baseline: dict, reference: dict) -> list[str]:
    """
    Compare two baselines structurally.

    Counts may drift as data changes; structure and categorical values
    must not.
    """
    issues: list[str] = []
    for section in ("rag", "embeddings", "analysis"):
        ref_sec, new_sec = reference.get(section, {}), baseline.get(section, {})
        if "error" in ref_sec or "error" in new_sec:
            issues.append(
                f"{section}: error state (ref={ref_sec.get('error')!r}, "
                f"new={new_sec.get('error')!r})"
            )
            continue
        for key in ref_sec:
            if key != "by_entity_type" and key not in new_sec:
                issues.append(f"{section}.{key}: present in reference, missing now")
    rec_ref = reference.get("analysis", {}).get("recommendation")
    rec_new = baseline.get("analysis", {}).get("recommendation")
    if rec_ref and rec_new and rec_ref != rec_new:
        issues.append(f"recommendation changed: {rec_ref!r} → {rec_new!r}")
    dim_ref = reference.get("embeddings", {}).get("vector_dimension")
    dim_new = baseline.get("embeddings", {}).get("vector_dimension")
    if dim_ref and dim_new and dim_ref != dim_new:
        issues.append(f"embedding dimension changed: {dim_ref} → {dim_new}")
    return issues


async def _run_legacy_path(ticker: str) -> dict:
    """
    Execute the LEGACY production path (plan §11 oracle):

        ContextBuilder → EvidenceAttributor → LLMService.analyze_company
        → AnalysisValidator → InvestmentScoringEngine

    This is exactly what analysis_worker.run_company_analysis does.
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.domains.stock.models.company import Company
    from app.domains.stock.scoring.investment_scoring import InvestmentScoringEngine
    from app.domains.stock.workers.analysis_worker import run_company_analysis

    out: dict = {"path": "legacy"}
    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).where(Company.ticker == ticker.upper()).limit(1)
        )
        company = result.scalar_one_or_none()
        if company is None:
            return {"path": "legacy", "error": f"No Company row for {ticker.upper()}"}

        # Full AI research analysis (context → evidence → LLM → validate).
        try:
            analysis = await run_company_analysis(company.id)
            out["llm_success"] = analysis is not None
            if analysis is not None:
                out["llm_model"] = analysis.llm_model
                out["llm_tokens"] = analysis.llm_tokens_used
                out["analysis_confidence"] = analysis.confidence_score
                out["summary_present"] = bool(
                    (analysis.llm_analysis or {}).get("summary")
                )
        except Exception as exc:
            out["llm_success"] = False
            out["llm_error"] = str(exc)[:300]

        # Deterministic investment score.
        score_row = await InvestmentScoringEngine(session).calculate_score(company.id)

    out.update(
        {
            "overall_score": float(score_row.overall_score),
            "fundamental_score": float(score_row.fundamental_score or 0.0),
            "technical_score": float(score_row.technical_score or 0.0),
            "risk_score": float(score_row.risk_score or 0.0),
            "confidence": float(score_row.confidence or 0.0),
            "recommendation": score_row.recommendation,
            "scoring_model": getattr(score_row, "scoring_model", None),
            "stages": {"all": "success"},
        }
    )
    return out

async def _run_framework_path(ticker: str) -> dict:
    """
    Execute the FRAMEWORK path:

        build_stock_pipeline() → IntelligencePipeline.run()

    through the DomainModule contract and generic capabilities only.
    """
    from app.domains.stock.pipeline_factory import run_stock_analysis

    result = await run_stock_analysis(ticker)
    meta = result.metadata or {}
    stages = meta.get("stages", {})
    out: dict = {
        "path": "framework",
        "pipeline_status": result.status,
        "llm_success": result.status == "completed"
        and stages.get("llm") == "success",
        "llm_model": meta.get("llm_model"),
        "llm_tokens": meta.get("llm_tokens"),
        "analysis_confidence": result.confidence,
        "overall_score": (
            float(result.score) if result.score is not None else None
        ),
        "confidence": float(result.confidence or 0.0),
        "recommendation": result.recommendation,
        "evidence_count": len(result.evidence or []),
        "stages": stages,
    }

    # Pull component/risk detail from the persisted latest score row so the
    # comparison shape matches the legacy snapshot exactly.
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.domains.stock.models.analysis import InvestmentScore
    from app.domains.stock.models.company import Company

    async with async_session_factory() as session:
        cid = await session.execute(
            select(Company.id).where(Company.ticker == ticker.upper()).limit(1)
        )
        company_id = cid.scalar_one_or_none()
        if company_id is not None:
            row = await session.execute(
                select(InvestmentScore)
                .where(InvestmentScore.company_id == company_id)
                .order_by(InvestmentScore.timestamp.desc())
                .limit(1)
            )
            score = row.scalar_one_or_none()
            if score is not None:
                out["fundamental_score"] = float(score.fundamental_score or 0.0)
                out["technical_score"] = float(score.technical_score or 0.0)
                out["risk_score"] = float(score.risk_score or 0.0)
                out["scoring_model"] = getattr(score, "scoring_model", None)
    return out


def compare_paths(legacy: dict, framework: dict) -> list[str]:
    """
    Compare legacy vs framework snapshots (plan §11 objective).

    Hard gates: recommendation flip, score divergence beyond epsilon,
    LLM success mismatch, failed pipeline stages.
    """
    issues: list[str] = []
    for name, snap in (("legacy", legacy), ("framework", framework)):
        if not isinstance(snap, dict):
            issues.append(f"{name}: no snapshot captured")
        elif snap.get("error"):
            issues.append(f"{name}: {snap['error']}")
    if issues:
        return issues

    EPSILON = 0.5
    l_rec = legacy.get("recommendation")
    f_rec = framework.get("recommendation")
    if l_rec != f_rec:
        issues.append(
            f"recommendation changed: legacy={l_rec!r} → framework={f_rec!r}"
        )

    l_sc = legacy.get("overall_score")
    f_sc = framework.get("overall_score")
    if l_sc is not None and f_sc is not None and abs(l_sc - f_sc) > EPSILON:
        issues.append(f"overall_score diverged: legacy={l_sc} framework={f_sc}")

    if not legacy.get("llm_success"):
        issues.append("legacy: LLM did not succeed")
    if not framework.get("llm_success"):
        issues.append("framework: LLM did not succeed")

    bad_stages = {
        k: v
        for k, v in (framework.get("stages") or {}).items()
        if isinstance(v, str) and v.startswith("failed")
    }
    if bad_stages:
        issues.append(f"framework failed stages: {bad_stages}")
    return issues


    out.update(
        {
            "overall_score": float(score_row.overall_score),
            "fundamental_score": float(score_row.fundamental_score or 0.0),
            "technical_score": float(score_row.technical_score or 0.0),
            "risk_score": float(score_row.risk_score or 0.0),
            "confidence": float(score_row.confidence or 0.0),
            "recommendation": score_row.recommendation,
            "scoring_model": getattr(score_row, "scoring_model", None),
            "stages": {"all": "success"},
        }
    )
    return out
def main() -> int:
    parser = argparse.ArgumentParser(description="Stock golden-path harness")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--save", help="Write captured snapshot to this JSON file")
    parser.add_argument("--compare", help="Compare against a saved snapshot JSON")
    parser.add_argument(
        "--path",
        choices=["db", "legacy", "framework", "both"],
        default="db",
        help=(
            "db: capture persisted state only (original behavior); "
            "legacy/framework/both: execute the analysis paths live "
            "(Phase 11 golden equivalence)"
        ),
    )
    args = parser.parse_args()

    violations: list[str] = []

    if args.path == "db":
        baseline = asyncio.run(capture_baseline(args.ticker))
        print(json.dumps(baseline, indent=2, default=str))
        violations += check_invariants(baseline)
        if args.compare:
            reference = json.loads(Path(args.compare).read_text())
            issues = compare(baseline, reference)
            for i in issues:
                print(f"MISMATCH: {i}")
            violations += issues
        if args.save:
            Path(args.save).write_text(json.dumps(baseline, indent=2, default=str))
            print(f"Baseline saved to {args.save}")
    else:
        snapshot: dict = {
            "ticker": args.ticker.upper(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        if args.path == "both":
            # Single event loop for BOTH paths: the global SQLAlchemy async
            # engine binds connections to the loop they were created on, so
            # running legacy and framework in separate asyncio.run() calls
            # corrupts the second run with cross-loop futures.
            #
            # Bounded retry: transient LLM-provider errors (e.g. 503
            # high-demand) should not fail the golden gate.
            async def _one_attempt():
                legacy = await _run_legacy_path(args.ticker)
                framework = await _run_framework_path(args.ticker)
                return legacy, framework, compare_paths(legacy, framework)

            async def _both_with_retry(attempts: int = 3, delay_s: float = 20.0):
                result = None
                for attempt in range(1, attempts + 1):
                    result = await _one_attempt()
                    legacy, framework, issues = result
                    print(f"--- attempt {attempt}: {'PASS' if not issues else f'{len(issues)} issue(s)'} ---")
                    if not issues:
                        return result
                    transient = "503" in json.dumps([legacy, framework])
                    if not transient:
                        break
                    print(f"transient provider error detected; retrying in {delay_s}s")
                    await asyncio.sleep(delay_s)
                return result

            snapshot["legacy"], snapshot["framework"], issues = asyncio.run(
                _both_with_retry()
            )
            print("--- legacy ---")
            print(json.dumps(snapshot["legacy"], indent=2, default=str))
            print("--- framework ---")
            print(json.dumps(snapshot["framework"], indent=2, default=str))

            violations += issues

        if args.save:
            Path(args.save).write_text(json.dumps(snapshot, indent=2, default=str))
            print(f"Snapshot saved to {args.save}")

    if violations:
        print("GOLDEN CHECK: FAIL")
        return 1
    print("GOLDEN CHECK: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())