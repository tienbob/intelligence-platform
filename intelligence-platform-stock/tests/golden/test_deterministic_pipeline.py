"""
Deterministic Stock pipeline test (Phase 12, §12.6 + §12.7).

LEVEL 2 of the verification stack:

    fixture → framework pipeline → real Stock domain objects → expected result

Real components: Stock manifest (prompts via analysis-type alias, context
builder, scoring strategy), AnalysisValidator, framework validation.
Faked: LLM transport (canned schema-valid response), RAG (fixture
buckets), DB session/engine (monkeypatched). Zero network, zero Gemini.

Run: PYTHONPATH=. pytest tests/golden/test_deterministic_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "aapl_pipeline.json").read_text()
)


# ── Fakes seeded from the fixture ────────────────────────────────

class _FakeRAG:
    async def retrieve_context(self, query, **kwargs):
        return FIXTURE["rag_context"]


class _FakeLLM:
    """
    Deterministic stand-in for Stock's LLMService.analyze contract,
    including the Stock-side structured-output validation that production
    runs inside analyze().
    """

    def __init__(self):
        self.calls = []

    async def analyze(self, system_prompt, context, user_query=None,
                      evidence_attributor=None, analysis_type="company",
                      prompt_name=None):
        self.calls.append({"prompt_name": prompt_name, "system_len": len(system_prompt)})
        from app.domains.stock.scoring.analysis_validator import (
            AnalysisValidationError,
            AnalysisValidator,
        )

        result = dict(FIXTURE["llm_response"])
        if evidence_attributor is not None:
            result["evidence"] = evidence_attributor.build_evidence_package(
                context.get("rag_context", {})
            )
        try:
            if analysis_type == "company":
                AnalysisValidator.validate_company_analysis(result)
        except AnalysisValidationError as exc:
            raise AssertionError(f"fixture LLM response invalid: {exc}") from exc
        return result


class _FakeScoreRow:
    id = 101
    overall_score = FIXTURE["scoring_result"]["overall_score"]
    confidence = FIXTURE["scoring_result"]["confidence"]
    recommendation = FIXTURE["scoring_result"]["recommendation"]
    fundamental_score = FIXTURE["scoring_result"]["fundamental_score"]
    technical_score = FIXTURE["scoring_result"]["technical_score"]
    risk_score = FIXTURE["scoring_result"]["risk_score"]
    valuation_score = 55.0
    growth_score = 60.0
    sentiment_score = 58.0
    catalyst_score = 52.0
    scoring_model = FIXTURE["scoring_result"]["scoring_model"]
    scoring_version = FIXTURE["scoring_result"]["scoring_version"]


class _FakeCompany:
    id = 42


class _FakeResolver:
    def __init__(self, session):
        pass

    async def resolve(self, ticker=None, **kw):
        return _FakeCompany()


class _FakeEngine:
    def __init__(self, session):
        pass

    async def calculate_score(self, company_id):
        return _FakeScoreRow()


class _FakeSessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


@pytest.fixture()
def patch_db(monkeypatch):
    import app.core.database as db
    import app.domains.stock.normalization.companies as companies_mod
    import app.domains.stock.scoring.investment_scoring as inv_mod
    import app.domains.stock.scoring.scoring_strategy as strategy_mod

    monkeypatch.setattr(
        strategy_mod, "async_session_factory", lambda: _FakeSessionCM()
    )
    monkeypatch.setattr(companies_mod, "EntityResolver", _FakeResolver)
    monkeypatch.setattr(inv_mod, "InvestmentScoringEngine", _FakeEngine)
    import app.domains.stock.providers.persisted as persisted
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    _FakeCompany.ticker = 'AAPL'
    for field, value in FIXTURE['domain_snapshots']['company'].items():
        setattr(_FakeCompany, field, value)
    reader = SimpleNamespace(macro_engine=SimpleNamespace(get_macro_snapshot=AsyncMock(return_value=FIXTURE['domain_snapshots']['macro_snapshot'])))
    for section in ('market', 'technical', 'fundamental', 'news', 'event', 'risk', 'anomaly'):
        setattr(reader, f'build_{section}_snapshot', AsyncMock(return_value=FIXTURE['domain_snapshots'][f'{section}_snapshot']))
    monkeypatch.setattr(persisted, 'async_session_factory', lambda: _FakeSessionCM())
    monkeypatch.setattr(persisted, 'EntityResolver', _FakeResolver)
    monkeypatch.setattr(persisted, 'StockSnapshotReader', lambda session: reader)
    # The pipeline uses the global engine indirectly through nothing else;
    # guard against accidental real connections.
    monkeypatch.setattr(db, "async_session_factory", lambda: (_ for _ in ()).throw(
        AssertionError("pipeline hit the real database")
    ))


# ── The Level-2 golden test ──────────────────────────────────────

def test_aapl_pipeline_fixture_end_to_end(patch_db):
    from app.domains.stock.manifest import StockDomain
    from app.intelligence.pipeline import IntelligencePipeline
    from app.shared.entities import AnalysisRequest, EntityRef

    llm = _FakeLLM()

    class _Registry:
        def get(self, name):
            assert name == "stock"
            return StockDomain()

    pipe = IntelligencePipeline(
        registry=_Registry(),
        rag_service=_FakeRAG(),
        llm_service=llm,
    )
    ref = FIXTURE["entity_ref"]
    result = asyncio.run(pipe.run(AnalysisRequest(
        entity_ref=EntityRef(**ref),
        analysis_type=FIXTURE["analysis_type"],
    )))

    exp = FIXTURE["expected"]
    assert result.status == exp["status"], result.summary
    assert result.summary == exp["summary"]
    assert result.score == pytest.approx(exp["overall_score"])
    assert result.confidence == pytest.approx(exp["confidence"])
    assert result.recommendation == exp["recommendation"]
    assert len(result.evidence) == exp["evidence_count"]

    assert result.metadata["domain_snapshots"] == FIXTURE["domain_snapshots"]
    assert result.metadata["llm_output"]["investment_thesis"] == FIXTURE["llm_response"]["investment_thesis"]
    assert result.metadata["scoring_metadata"]["score_id"] == 101
    stages = result.metadata["stages"]
    assert list(stages) == [
        "entity_resolution", "ingestion", "normalization", "evidence",
        "rag", "context", "llm", "validation", "scoring",
    ]
    if exp["all_stages_success"]:
        assert all(v == "success" for v in stages.values()), stages

    # Entity was normalized through the framework resolver.
    assert result.entity_ref.entity_id == "AAPL"

    # Real Stock prompt reached the fake LLM via the analysis-type alias.
    assert llm.calls, "LLM was not invoked"
    assert llm.calls[0]["system_len"] > 200  # real company_analysis prompt
