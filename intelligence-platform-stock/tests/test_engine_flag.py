"""Gate 5.1 — Framework is the production analysis engine (docs/PLAN.md §5.1).

Both production entry points route through execute_company_analysis(), which
always delegates to the framework path (Gate 6 cleanup removed legacy fallback).
Fakes only — no LLM quota.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.stock.services import company_analysis as ca  # noqa: E402
from app.shared.entities import AnalysisResult, EntityRef  # noqa: E402

TICKER = "AAPL"


class _FakeCompany:
    id = 7
    ticker = TICKER


def _fake_pipeline_result():
    return AnalysisResult(
        entity_ref=EntityRef("stock", "company", TICKER),
        status="completed",
        summary="framework summary",
        score=71.5,
        confidence=0.91,
        recommendation="WATCH",
        insights=[{"text": "i"}],
        risks=["r"],
        metadata={
            "llm_model": "fake-model",
            "llm_provider": "fake",
            "prompt_name": "stock_company",
            "prompt_version": "1.0",
            "analysis_type": "company",
            "llm_tokens": 42,
            "stages": {"llm": "success"},
            "domain_snapshots": {
                "market_snapshot": {}, "fundamental_snapshot": {},
                "technical_snapshot": {}, "news_snapshot": {},
                "macro_snapshot": {}, "risk_snapshot": {},
            },
        },
    )


class _FakePipeline:
    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return _fake_pipeline_result()


class _FakeScore:
    overall_score = 71.5
    risk_score = 28.5
    confidence = 0.9


class _PersistSession:
    """Just enough session for persist_analysis()."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        from app.domains.stock.models.analysis import Analysis

        if isinstance(obj, Analysis) and obj.id is None:
            obj.id = 500
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _install_framework_fake(monkeypatch):
    pipe = _FakePipeline()
    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda: pipe)

    async def loader(session, company_id):
        assert company_id == 7
        return _FakeScore()

    return pipe, loader


# ── Framework routing ──────────────────────────────────────────


def test_framework_engine_routes_to_pipeline(monkeypatch):
    pipe, loader = _install_framework_fake(monkeypatch)
    session = _PersistSession()
    res = asyncio.run(ca.execute_company_analysis(
        session, _FakeCompany(), score_loader=loader,
    ))
    assert pipe.requests and pipe.requests[0].entity_ref.entity_id == TICKER
    assert res.analysis.investment_score == 71.5
    assert res.llm_output["_meta"]["model"] == "fake-model"
    ca.assert_completed_analysis_contract(res.analysis)


def test_both_entry_points_use_framework(monkeypatch):
    """Entry-point neutrality: API-style (existing row + stages) and
    worker-style (no row) both hit the framework pipeline."""
    pipe, loader = _install_framework_fake(monkeypatch)
    existing = SimpleNamespace(analysis_id="x", id=9, status="collecting_data")
    stages = []

    async def on_stage(name):
        stages.append(name)

    async def api_style():
        await ca.execute_company_analysis(
            _PersistSession(), _FakeCompany(),
            existing=existing, on_stage=on_stage,
            score_loader=loader,
        )

    async def worker_style():
        await ca.execute_company_analysis(
            _PersistSession(), _FakeCompany(),
            score_loader=loader,
        )

    asyncio.run(api_style())
    asyncio.run(worker_style())
    assert len(pipe.requests) == 2
    assert "calculating_metrics" in stages      # API stage reporting preserved


def test_framework_failure_raises(monkeypatch):
    class _FailPipe:
        async def run(self, request):
            return AnalysisResult(
                entity_ref=request.entity_ref, status="failed",
                metadata={"stages": {"llm": "failed: boom"}},
            )

    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda: _FailPipe())

    async def go():
        try:
            await ca._execute_framework(
                _PersistSession(), _FakeCompany(),
                existing=None, on_stage=None,
                score_loader=lambda s, c: _FakeScore(),
            )
        except RuntimeError as exc:
            return "boom" in str(exc)
        return False

    assert asyncio.run(go()) is True


if __name__ == "__main__":
    print("run via pytest")
