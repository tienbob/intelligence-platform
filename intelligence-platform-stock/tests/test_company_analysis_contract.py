"""Canonical Analysis contract test (docs/PLAN_ANALYSIS_CONTRACT.md).

Whatever entry point creates an analysis — API background task or worker /
Gate-3 legacy oracle — a persisted ``status == "completed"`` row MUST carry
the same complete contract: deterministic scores, provenance, snapshot
columns, duration, and one AnalysisSource row per source-backed claim.

Regression guard for bugs produced by duplicated orchestration
(null investment_score / risk_score on Gate-3-created rows).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.stock.models.analysis import AnalysisSource  # noqa: E402
from app.domains.stock.services.company_analysis import (  # noqa: E402
    CompanyAnalysisService,
    assert_completed_analysis_contract,
)


CONTEXT = {
    "rag_context": {"news": [{"id": 1}]},
    "entity": {},
    "market_snapshot": {}, "fundamental_snapshot": {}, "technical_snapshot": {},
    "news_snapshot": {}, "macro_snapshot": {}, "risk_snapshot": {},
}


class _FakeContextBuilder:
    def __init__(self, session=None):
        pass

    async def build_full_context(self, company, **kwargs):
        return CONTEXT


class _FakeAttributor:
    def __init__(self):
        self.registered = None

    def register_sources(self, rag):
        self.registered = rag
        return []


class _FakeScore:
    overall_score = 64.4
    risk_score = 35.6
    confidence = 0.88


class _FakeScoringEngine:
    def __init__(self, session):
        pass

    async def calculate_score(self, company_id):
        assert company_id == 7
        return _FakeScore()


def _fake_llm_output():
    return {
        "summary": "s",
        "confidence": 0.7,  # LLM self-report — must NOT become confidence_score
        "source_backed_claims": [
            {"claim": "c1",
             "source": {"type": "t", "source": "SEC", "value": "12%", "period": "2026-Q2"}},
            {"claim": "c2",
             "source": {"type": "t2", "source": "massive", "value": 3.5}},
        ],
        "evidence": {"evidence_sources": [{"source_id": "news_1"}], "source_count": 1},
        "_meta": {"prompt_version": "1.0", "model": "fake", "tokens_used": 5},
    }


class _FakeLLM:
    def __init__(self):
        self.calls = []

    async def analyze_company(self, context, evidence_attributor=None):
        self.calls.append({"context": context, "attributor": evidence_attributor})
        return _fake_llm_output()


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        # Simulate the ORM flush assigning an autoincrement PK to new
        # Analysis rows — guards against child rows referencing a pre-flush
        # None id (real NotNullViolation caught live on analysis_sources).
        from app.domains.stock.models.analysis import Analysis

        if isinstance(obj, Analysis) and obj.id is None:
            obj.id = 9000 + len(self.added)
        self.added.append(obj)

    async def execute(self, statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


class _FakeCompany:
    id = 7
    ticker = "AAPL"


def _service(session, llm):
    attributors = []

    def factory():
        a = _FakeAttributor()
        attributors.append(a)
        return a

    svc = CompanyAnalysisService(
        session,
        context_builder=_FakeContextBuilder(),
        llm_service=llm,
        evidence_attributor_factory=factory,
        scoring_engine_factory=_FakeScoringEngine,
    )
    return svc, attributors


# ── Mode A: worker semantics (no existing row → create complete row) ──

def test_worker_mode_produces_full_contract_row():
    session = _FakeSession()
    llm = _FakeLLM()
    svc, attributors = _service(session, llm)

    result = asyncio.run(svc.execute(company=_FakeCompany()))
    analysis = result.analysis

    assert_completed_analysis_contract(analysis)
    assert analysis.analysis_id and len(analysis.analysis_id) == 36
    assert analysis.investment_score == 64.4
    assert analysis.risk_score == 35.6
    assert analysis.confidence_score == 0.88  # engine value, NOT llm 0.7

    # §32 wiring always-on: attributor saw rag context; LLM received it.
    assert len(attributors) == 1
    assert attributors[0].registered == CONTEXT["rag_context"]
    assert llm.calls[0]["attributor"] is attributors[0]
    assert llm.calls[0]["context"] == CONTEXT

    # Source rows: one per claim; "12%" coerced to 12.0; FK id assigned
    # (non-null) — guards the pre-flush None-id bug caught live.
    sources = [a for a in session.added if isinstance(a, AnalysisSource)]
    assert len(sources) == 2
    assert sources[0].value == 12.0 and sources[1].value == 3.5
    assert all(s.analysis_id is not None for s in sources)
    assert all(s.analysis_id == analysis.id for s in sources)


# ── Mode B: API semantics (existing row updated in place) ───────────

def test_api_existing_row_mode_satisfies_same_contract():
    session = _FakeSession()
    llm = _FakeLLM()
    svc, _ = _service(session, llm)

    existing = SimpleNamespace(
        analysis_id="existing-1", id=42, status="collecting_data",
        investment_score=None, risk_score=None,
    )
    session.existing = existing
    stages = []

    async def on_stage(name):
        stages.append(name)

    async def run():
        return await svc.execute(
            company=_FakeCompany(),
            existing=existing,
            include_news=False,
            on_stage=on_stage,
        )

    result = asyncio.run(run())
    analysis = result.analysis

    assert analysis is existing  # updates in place, does not create
    assert_completed_analysis_contract(analysis)  # SAME contract as mode A
    assert stages == [
        "calculating_metrics",
        "retrieving_context",
        "llm_analysis",
        "risk_analysis",
    ]
    assert result.score.overall_score == 64.4


if __name__ == "__main__":
    test_worker_mode_produces_full_contract_row()
    test_api_existing_row_mode_satisfies_same_contract()
    print("CONTRACT TESTS PASS")

