"""Gate 5.1 — ANALYSIS_ENGINE flag (docs/PLAN.md §5.1).

Both production entry points route through execute_company_analysis(), the
single reader of the flag; flipping it must switch BOTH, and each engine must
satisfy the canonical persisted contract. Fakes only — no LLM quota.
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
            "scoring_metadata": {"score_id": 101},
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
    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda **kw: pipe)

    async def loader(session, company_id, score_id):
        assert score_id == 101
        assert company_id == 7
        return _FakeScore()

    return pipe, loader


# ── Flag routing ─────────────────────────────────────────────────


def test_legacy_engine_routes_to_service(monkeypatch):
    calls = {}

    class _Svc:
        async def execute(self, *, company, **kw):
            calls["ran"] = company.ticker
            return SimpleNamespace(analysis=SimpleNamespace(status="completed"))

    res = asyncio.run(ca.execute_company_analysis(
        None, _FakeCompany(), legacy_service=_Svc(), engine="legacy",
    ))
    assert calls["ran"] == TICKER
    assert res.analysis.status == "completed"


def test_framework_engine_routes_to_pipeline(monkeypatch):
    pipe, loader = _install_framework_fake(monkeypatch)
    session = _PersistSession()
    res = asyncio.run(ca.execute_company_analysis(
        session, _FakeCompany(), engine="framework", score_loader=loader,
    ))
    assert pipe.requests and pipe.requests[0].entity_ref.entity_id == TICKER
    assert res.analysis.investment_score == 71.5
    assert res.llm_output["_meta"]["model"] == "fake-model"
    ca.assert_completed_analysis_contract(res.analysis)


def test_flag_flip_switches_engine(monkeypatch):
    """PLAN.md §5.1: legacy→framework AND framework→legacy, repeatedly."""
    ran = []
    pipe, loader = _install_framework_fake(monkeypatch)

    class _Svc:
        async def execute(self, *, company, **kw):
            ran.append("legacy")
            return SimpleNamespace(analysis=None)

    async def go(engine):
        await ca.execute_company_analysis(
            _PersistSession(), _FakeCompany(),
            legacy_service=_Svc(), engine=engine, score_loader=loader,
        )

    asyncio.run(go("legacy"))
    asyncio.run(go("framework"))
    asyncio.run(go("legacy"))
    asyncio.run(go("framework"))
    assert ran == ["legacy", "legacy"]          # service used twice
    assert len(pipe.requests) == 2              # pipeline used twice


def test_both_wrappers_respect_framework_flag(monkeypatch):
    """Entry-point neutrality: API-style (existing row + stages) and
    worker-style (no row) both hit the pipeline when flag says framework."""
    pipe, loader = _install_framework_fake(monkeypatch)
    existing = SimpleNamespace(analysis_id="x", id=9, status="collecting_data")
    stages = []

    async def on_stage(name):
        stages.append(name)

    async def execute(statement):
        return SimpleNamespace(scalar_one_or_none=lambda: existing)

    session = _PersistSession()
    session.execute = execute

    async def api_style():
        await ca.execute_company_analysis(
            session, _FakeCompany(),
            existing=existing, on_stage=on_stage,
            engine="framework", score_loader=loader,
        )

    async def worker_style():
        await ca.execute_company_analysis(
            _PersistSession(), _FakeCompany(),
            engine="framework", score_loader=loader,
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

    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda **kw: _FailPipe())

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



def test_framework_preserves_complete_llm_response_and_claim_rows(monkeypatch):
    from app.domains.stock.models.analysis import AnalysisSource
    pipe, loader = _install_framework_fake(monkeypatch)
    result = _fake_pipeline_result()
    payload = {
        'summary': 'Full response', 'confidence': 0.72, 'investment_thesis': 'Preserved thesis',
        'bull_case': ['Bull case'], 'bear_case': ['Bear case'],
        'source_backed_claims': [{'claim': 'Revenue grew', 'source': {'type': 'financial', 'source': 'SEC', 'metric': 'revenue', 'value': 123, 'period': '2026-Q2'}}],
        'evidence': {'evidence_sources': [{'id': 'news_1', 'source_name': 'finnhub'}], 'source_count': 1},
        '_meta': {'model': 'fake-model', 'provider': 'fake', 'prompt_version': '1.0', 'tokens_used': 42},
    }
    result.metadata['llm_output'] = payload
    result.metadata['rag_context'] = {'news': [{'id': 1}]}
    async def run(request): return result
    pipe.run = run
    session = _PersistSession()
    saved = asyncio.run(ca.execute_company_analysis(session, _FakeCompany(), engine='framework', score_loader=loader))
    assert saved.analysis.llm_analysis['investment_thesis'] == 'Preserved thesis'
    assert saved.analysis.llm_analysis['confidence'] == 0.72
    assert saved.analysis.confidence_score == 0.9
    assert saved.analysis.llm_analysis['_evidence'] == payload['evidence']
    assert saved.analysis.llm_analysis['_input_context']['rag_context'] == {'news': [{'id': 1}]}
    claims = [row for row in session.added if isinstance(row, AnalysisSource)]
    assert len(claims) == 1
    assert claims[0].claim == 'Revenue grew'
    assert claims[0].source_name == 'SEC'
