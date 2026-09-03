"""Canonical Analysis contract test (docs/PLAN_ANALYSIS_CONTRACT.md).

Gate 6/8: both production entry points (API + worker) run through
``execute_company_analysis()`` → the framework path → ``persist_analysis()``.
Whatever entry point creates an analysis, a persisted
``status == "completed"`` row MUST carry the same complete contract:
deterministic scores, provenance, snapshot columns, duration, AND one
AnalysisSource row per source-backed claim (§32) with the RAG-attributed
evidence package.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.stock.models.analysis import AnalysisSource  # noqa: E402
from app.domains.stock.services import company_analysis as ca  # noqa: E402
from app.shared.entities import AnalysisResult, EntityRef  # noqa: E402

TICKER = "AAPL"

SNAPSHOTS = {
    "market_snapshot": {"latest_price": 175.5},
    "fundamental_snapshot": {"revenue": 394000000000},
    "technical_snapshot": {"momentum_1d_pct": 1.2},
    "news_snapshot": {"news_count": 1, "recent_news": [{"title": "t"}]},
    "macro_snapshot": {"indicators": {"fed_funds_rate": 4.5}},
    "risk_snapshot": {"risk_score": None},
}

CLAIMS = [
    {"claim": "c1",
     "source": {"type": "t", "source": "SEC", "value": "12%", "period": "2026-Q2"}},
    {"claim": "c2",
     "source": {"type": "t2", "source": "massive", "value": 3.5}},
]

LLM_EVIDENCE = {
    "evidence_sources": [{"source_id": "news_1"}],
    "source_count": 1,
}


def _pipeline_result():
    return AnalysisResult(
        entity_ref=EntityRef("stock", "company", TICKER),
        status="completed",
        summary="framework summary",
        score=64.4,
        confidence=0.88,
        recommendation="WATCH",
        insights=[{"text": "i"}],
        risks=["r"],
        metadata={
            "llm_model": "fake",
            "llm_provider": "fake",
            "prompt_name": "stock_company",
            "prompt_version": "1.0",
            "analysis_type": "company",
            "llm_tokens": 5,
            "stages": {"llm": "success"},
            "domain_snapshots": SNAPSHOTS,
            "source_backed_claims": CLAIMS,
            "llm_evidence": LLM_EVIDENCE,
        },
    )


class _FakePipeline:
    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return _pipeline_result()


class _FakeScore:
    overall_score = 64.4
    risk_score = 35.6
    confidence = 0.88


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        # Simulate ORM flush assigning the autoincrement PK to new Analysis
        # rows — guards child rows referencing a pre-flush None id.
        from app.domains.stock.models.analysis import Analysis

        if isinstance(obj, Analysis) and obj.id is None:
            obj.id = 9000 + len(self.added)
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


class _FakeCompany:
    id = 7
    ticker = TICKER


def _install(monkeypatch):
    pipe = _FakePipeline()
    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda: pipe)

    async def loader(session, company_id):
        assert company_id == 7
        return _FakeScore()

    return pipe, loader


# ── Mode A: worker semantics (no existing row → create complete row) ──

def test_worker_mode_produces_full_contract_row(monkeypatch):
    pipe, loader = _install(monkeypatch)
    session = _FakeSession()

    result = asyncio.run(ca.execute_company_analysis(
        session, _FakeCompany(), score_loader=loader,
    ))
    analysis = result.analysis

    ca.assert_completed_analysis_contract(analysis)
    assert analysis.analysis_id and len(analysis.analysis_id) == 36
    assert analysis.investment_score == 64.4
    assert analysis.risk_score == 35.6
    assert analysis.confidence_score == 0.88  # engine value, NOT llm 0.7
    assert len(pipe.requests) == 1
    assert pipe.requests[0].entity_ref.entity_id == TICKER

    # §32: source-backed claims persisted as AnalysisSource rows, one per
    # claim; "12%" coerced to 12.0; FK id assigned (non-null) — guards the
    # pre-flush None-id bug caught live.
    sources = [a for a in session.added if isinstance(a, AnalysisSource)]
    assert len(sources) == 2
    assert sources[0].value == 12.0 and sources[1].value == 3.5
    assert all(s.analysis_id == analysis.id for s in sources)

    # RAG-attributed evidence package persisted on the row.
    assert result.evidence_package == LLM_EVIDENCE


# ── Mode B: API semantics (existing row updated in place) ───────────

def test_api_existing_row_mode_satisfies_same_contract(monkeypatch):
    pipe, loader = _install(monkeypatch)
    session = _FakeSession()

    existing = SimpleNamespace(
        analysis_id="existing-1", id=42, status="collecting_data",
        investment_score=None, risk_score=None,
    )
    stages = []

    async def on_stage(name):
        stages.append(name)

    async def run():
        return await ca.execute_company_analysis(
            session, _FakeCompany(),
            existing=existing, on_stage=on_stage,
            score_loader=loader,
        )

    result = asyncio.run(run())
    analysis = result.analysis

    assert analysis is existing  # updates in place, does not create
    ca.assert_completed_analysis_contract(analysis)  # SAME contract as mode A
    assert "calculating_metrics" in stages
    assert result.score.overall_score == 64.4
    # Same claim/evidence fidelity on the API path.
    sources = [a for a in session.added if isinstance(a, AnalysisSource)]
    assert len(sources) == 2


if __name__ == "__main__":
    test_worker_mode_produces_full_contract_row(None)
    print("run via pytest")
