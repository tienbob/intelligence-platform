"""Regression: the legacy analysis worker must persist a valid Analysis row.

Gate 3 (live LLM equivalence) caught a real bug: ``Analysis.analysis_id`` is
unique + NOT NULL with no default, and ``run_company_analysis`` never set it.
Any analysis that passed schema validation (SPY/SKHY in the live matrix) then
died on flush with a NotNullViolationError, so the legacy oracle could never
persist a successful analysis. The API endpoint sets ``uuid4()``; the worker
now does too.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.stock.workers.analysis_worker import run_company_analysis


class _FakeCompany:
    id = 7
    ticker = "SPY"


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    async def get(self, model, ident):
        return _FakeCompany()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


class _FakeSessionCM:
    def __init__(self, session):
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *exc):
        return False


class _FakeContextBuilder:
    def __init__(self, session=None):
        pass

    async def build_full_context(self, company, **kwargs):
        return {
            "rag_context": {"news": [], "filings": []},
            "entity": {},
            "market_snapshot": {},
            "fundamental_snapshot": {},
            "technical_snapshot": {},
            "news_snapshot": {},
            "macro_snapshot": {},
            "risk_snapshot": {},
        }


class _FakeAttributor:
    def register_sources(self, rag):
        return []


class _FakeScore:
    overall_score = 77.7
    risk_score = 21.3
    confidence = 0.9


class _FakeScoringEngine:
    def __init__(self, session):
        pass

    async def calculate_score(self, company_id):
        return _FakeScore()


class _FakeLLM:
    async def analyze_company(self, context, evidence_attributor=None):
        return {
            "summary": "test",
            "confidence": 0.8,
            "evidence": {"evidence_sources": [], "source_count": 0},
            "_meta": {"prompt_version": "1.0", "model": "fake", "tokens_used": 1},
        }


def test_run_company_analysis_sets_analysis_id(monkeypatch):
    import app.domains.stock.workers.analysis_worker as aw

    session = _FakeSession()
    monkeypatch.setattr(aw, "async_session_factory", lambda: _FakeSessionCM(session))
    monkeypatch.setattr(aw, "ContextBuilder", _FakeContextBuilder)
    monkeypatch.setattr(aw, "EvidenceAttributor", _FakeAttributor)
    monkeypatch.setattr(aw, "LLMService", lambda: _FakeLLM())
    monkeypatch.setattr(aw, "InvestmentScoringEngine", _FakeScoringEngine)

    analysis = asyncio.run(run_company_analysis(7))
    assert analysis is not None
    assert isinstance(analysis.analysis_id, str)
    assert len(analysis.analysis_id) == 36  # uuid4() hex
    assert session.commits == 1

    # Canonical contract (docs/PLAN_ANALYSIS_CONTRACT.md): deterministic
    # scoring columns must be populated by the shared core regardless of
    # entry point — this is the regression for the null-score bug.
    assert analysis.investment_score == 77.7
    assert analysis.risk_score == 21.3
    assert analysis.confidence_score == 0.9
    assert analysis.analysis_version == "1.0"
    assert analysis.prompt_version == "1.0"
    assert analysis.llm_model == "fake"
    assert analysis.llm_tokens_used == 1
    assert analysis.duration_seconds is not None
    assert analysis.status == "completed"
    assert analysis.market_snapshot == {}

