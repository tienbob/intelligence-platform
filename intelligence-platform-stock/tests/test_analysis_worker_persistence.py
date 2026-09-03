"""Regression: the worker must persist a valid Analysis row through the framework path.

Gate 6.2: Worker delegates analysis execution to the framework path via
execute_company_analysis(engine="framework"). This test verifies the worker
still produces a valid Analysis row with all canonical contract fields populated.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.stock.services import company_analysis as ca
from app.domains.stock.workers.analysis_worker import run_company_analysis
from app.shared.entities import AnalysisResult, EntityRef


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


class _FakePipeline:
    async def run(self, request):
        return AnalysisResult(
            entity_ref=EntityRef("stock", "company", "SPY"),
            status="completed",
            summary="framework summary",
            score=77.7,
            confidence=0.9,
            recommendation="WATCH",
            insights=[{"text": "i"}],
            risks=["r"],
            metadata={
                "llm_model": "fake",
                "llm_provider": "fake",
                "prompt_name": "stock_company",
                "prompt_version": "1.0",
                "analysis_type": "company",
                "llm_tokens": 1,
                "stages": {"llm": "success"},
                "domain_snapshots": {
                    "market_snapshot": {}, "fundamental_snapshot": {},
                    "technical_snapshot": {}, "news_snapshot": {},
                    "macro_snapshot": {}, "risk_snapshot": {},
                },
            },
        )


class _FakeScore:
    overall_score = 77.7
    risk_score = 21.3
    confidence = 0.9


def test_run_company_analysis_sets_analysis_id(monkeypatch):
    import app.domains.stock.workers.analysis_worker as aw

    session = _FakeSession()
    monkeypatch.setattr(aw, "async_session_factory", lambda: _FakeSessionCM(session))

    # Mock the framework pipeline
    pipe = _FakePipeline()
    monkeypatch.setattr(ca, "_build_framework_pipeline", lambda: pipe)

    async def fake_loader(session, company_id):
        return _FakeScore()

    monkeypatch.setattr(ca, "_load_latest_score", fake_loader)

    analysis = asyncio.run(run_company_analysis(7))
    assert analysis is not None
    assert isinstance(analysis.analysis_id, str)
    assert len(analysis.analysis_id) == 36  # uuid4() hex
    assert session.commits == 1

    # Canonical contract (docs/PLAN_ANALYSIS_CONTRACT.md): deterministic
    # scoring columns must be populated by the framework regardless of
    # entry point.
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

