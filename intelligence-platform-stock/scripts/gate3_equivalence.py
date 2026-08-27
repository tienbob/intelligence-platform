"""Gate 3 - live LLM equivalence (legacy vs framework) over the six reference
tickers in a SINGLE event loop (cross-loop SQLAlchemy bindings corrupt runs if
split across asyncio.run calls). See CHECKLIST Gate 3.

Legacy path = production worker (the equivalence oracle).
Framework path = build_stock_pipeline() with an LLM probe that captures the
Section-32 evidence package built inside LLMService.analyze.

Quota-aware: the Gemini free-tier embedding endpoint allows 100 req/min, which
the live RAG throttles; sleep between tickers and retry once on quota-looking
failures so the run is "not blocked by quota".

Run inside the app container (repo volume-mounted at /app):
  docker exec intelligence_stock_python sh -c \
    'cd /app && PYTHONPATH=/app python /app/scripts/gate3_equivalence.py'
"""
from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import select

from app.core.database import async_session_factory
from app.domains.stock.models.analysis import InvestmentScore
from app.domains.stock.models.company import Company
from tests.golden.stock_analysis import _run_legacy_path, compare_paths

REFERENCE_TICKERS = ["AAPL", "NVDA", "MSFT", "TSLA", "SPY", "SKHY"]
QUOTA_PAUSE = float(os.environ.get("GATE3_PAUSE", "70"))
TRANSIENT = ("429", "RESOURCE_EXHAUSTED", "Quota", "rate-limits")


async def latest_score_row(ticker):
    async with async_session_factory() as s:
        cid = (await s.execute(
            select(Company.id).where(Company.ticker == ticker)
        )).scalar_one_or_none()
        if cid is None:
            return None, {"present": False}
        sc = (await s.execute(
            select(InvestmentScore)
            .where(InvestmentScore.company_id == cid)
            .order_by(InvestmentScore.timestamp.desc()).limit(1)
        )).scalar_one_or_none()
        return sc, {"present": True, "scored": sc is not None}


class _Probe:
    """Transparent LLM wrapper that captures the engine's returned dict.

    The pipeline forwards a domain-provided ``evidence_attributor`` into
    StockLLMService.analyze, which then attaches ``result["evidence"]``
    (source-attributed claims) — that package is what we record per ticker.
    """

    def __init__(self, inner):
        self.inner = inner
        self.last = None

    async def analyze(self, *a, **kw):
        out = await self.inner.analyze(*a, **kw)
        self.last = out
        return out


async def framework_snapshot(ticker):
    from app.domains.stock.pipeline_factory import build_stock_pipeline
    from app.domains.stock.scoring.llm import LLMService
    from app.shared.entities import AnalysisRequest, EntityRef

    probe = _Probe(LLMService())
    pipe = build_stock_pipeline(llm_service=probe)
    res = await pipe.run(AnalysisRequest(
        entity_ref=EntityRef("stock", "company", ticker),
        analysis_type="company",
    ))
    meta = res.metadata or {}
    stages = meta.get("stages", {})
    evidence_pkg = (probe.last or {}).get("evidence", {}) or {}
    ev_sources = evidence_pkg.get("evidence_sources", [])
    snap = {
        "evidence_attribute_count": len(ev_sources),
        "evidence_source_types": (evidence_pkg.get("source_types") or [])[:5],
        "llm_tokens": meta.get("llm_tokens"),
        "prompt_name": meta.get("prompt_name"),
        "llm_provider": meta.get("llm_provider"),
        "stages": stages,
        "llm_success": res.status == "completed" and stages.get("llm") == "success",
        "overall_score": float(res.score) if res.score is not None else None,
        "recommendation": res.recommendation,
    }
    return res, snap


async def pair(ticker):
    legacy = await _run_legacy_path(ticker)
    result, fw = await framework_snapshot(ticker)
    sc, db = await latest_score_row(ticker)
    if sc is not None:
        fw.update({
            "fundamental_score": float(sc.fundamental_score or 0.0),
            "technical_score": float(sc.technical_score or 0.0),
            "risk_score": float(sc.risk_score or 0.0),
        })
    fw["pipeline_status"] = result.status
    fw["analysis_confidence"] = result.confidence
    fw["confidence"] = float(result.confidence or 0.0)
    issues = compare_paths(legacy, fw)
    semantic = {
        "summary": (result.summary or "")[:700],
        "insights": (result.insights or [])[:3],
        "risks": (result.risks or [])[:3],
    }
    return legacy, fw, db, issues, semantic


async def main():
    print(f"Reference matrix: {REFERENCE_TICKERS}  (quota pause={QUOTA_PAUSE}s)")
    report = {}
    for i, t in enumerate(REFERENCE_TICKERS):
        if i:
            print(f"...quota pause {QUOTA_PAUSE}s before {t}")
            await asyncio.sleep(QUOTA_PAUSE)
        legacy, fw, db, issues, semantic = await pair(t)
        if issues and any(k in json.dumps([legacy, fw], default=str)
                          for k in TRANSIENT):
            print(f"...quota-retry {t}")
            await asyncio.sleep(QUOTA_PAUSE)
            legacy, fw, db, issues, semantic = await pair(t)
        report[t] = {"db": db, "legacy": legacy, "framework": fw,
                     "issues": issues, "semantic": semantic,
                     "evidence_attribution_count": fw.get("evidence_attribute_count")}
        print("=" * 68)
        print(f"TICKER {t}  db={db}")
        print(f"  legacy    rec={legacy.get('recommendation')} "
              f"score={legacy.get('overall_score')} llm={legacy.get('llm_success')} "
              f"fund={legacy.get('fundamental_score')}")
        print(f"  framework rec={fw.get('recommendation')} "
              f"score={fw.get('overall_score')} llm={fw.get('llm_success')} "
              f"status={fw.get('pipeline_status')} "
              f"evid_attr={fw.get('evidence_attribute_count')} "
              f"prov={fw.get('llm_provider')}")
        bad = {k: v for k, v in fw.get("stages", {}).items()
               if not (isinstance(v, str) and v == "success")}
        print(f"  framework non-success stages: {bad or 'NONE'}")
        print(f"  validator/validation stage: {fw.get('stages', {}).get('validation')}")
        print(f"  hard-gate issues: {issues if issues else 'NONE (PASS)'}")
        print(f"  summary: {semantic['summary'][:180]}")

    print("=" * 68)
    n_ok = sum(1 for r in report.values() if not r.get("issues"))
    print(f"GATE 3 RESULT: {n_ok}/{len(REFERENCE_TICKERS)} hard-gate PASS")
    for t in REFERENCE_TICKERS:
        r = report.get(t, {})
        print(f"  {t}: {'PASS' if not r.get('issues') else 'FAIL'} "
              f"{str(r.get('issues', ''))[:150]}")
    with open("/tmp/gate3_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("Full report -> /tmp/gate3_report.json")


if __name__ == "__main__":
    asyncio.run(main())