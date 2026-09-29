"""Regression coverage for analysis ownership, cancellation and score history."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.domains.stock.api import analysis as api
from app.domains.stock.schemas.analysis import AnalysisRequest
from app.domains.stock.services.company_analysis import AnalysisCancelled
from tests.test_company_analysis_contract import _FakeCompany, _FakeLLM, _FakeSession, _service


def request():
    return Request({"type": "http", "headers": [
        (b"x-user-id", b"2"), (b"x-user-role", b"USER")], "method": "POST", "path": "/"})


def result(row):
    return SimpleNamespace(scalar_one_or_none=lambda: row)


def test_regular_user_cannot_delete_shared_analysis():
    db = AsyncMock()
    db.execute.return_value = result(SimpleNamespace(user_id=None))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.delete_analysis("shared", request(), db))
    assert exc.value.status_code == 404
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_untracked_company_uses_ingestion(monkeypatch):
    from app.domains.stock.api import stocks
    ingest = AsyncMock(return_value=None)
    monkeypatch.setattr(stocks, "_auto_ingest_ticker", ingest)
    db = AsyncMock()
    db.execute.return_value = result(None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.create_company_analysis(
            AnalysisRequest(ticker="NEW"), BackgroundTasks(), request(), db))
    assert exc.value.status_code == 404
    ingest.assert_awaited_once_with("NEW", db)


def test_cancellation_during_llm_prevents_completion():
    session = _FakeSession()
    existing = SimpleNamespace(analysis_id="job", id=42, status="llm_analysis")
    session.existing = existing

    class CancellingLLM(_FakeLLM):
        async def analyze_company(self, *args, **kwargs):
            existing.status = "cancelled"
            return await super().analyze_company(*args, **kwargs)

    svc, _ = _service(session, CancellingLLM())
    with pytest.raises(AnalysisCancelled):
        asyncio.run(svc.execute(company=_FakeCompany(), existing=existing))
    assert existing.status == "cancelled"
    assert session.commits == 0
    assert not session.added


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("confidence", [0.7, "0.7", None])
def test_detail_uses_only_its_own_score_snapshot(legacy, confidence):
    session = _FakeSession()
    svc, _ = _service(session, _FakeLLM())
    analysis = asyncio.run(svc.execute(company=_FakeCompany())).analysis
    analysis.user_id = 2
    analysis.created_at = None
    analysis.llm_analysis["confidence"] = confidence
    if legacy:
        del analysis.llm_analysis["_score_snapshot"]
    else:
        analysis.llm_analysis["_score_snapshot"].update(
            recommendation="BUY", fundamental_score=80, data_quality_score=0.9)
    db = AsyncMock()
    db.execute.side_effect = [result(analysis), result(_FakeCompany()),
                              SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))]
    response = asyncio.run(api.get_analysis(analysis.analysis_id, request(), db))
    if legacy:
        assert response.recommendation is None
        assert response.confidence_breakdown is None
    else:
        assert response.recommendation.recommendation == "BUY"
        assert response.recommendation.score == 64.4
        assert response.confidence_breakdown.data == 0.9
    assert response.investment_score == 64.4
    assert db.execute.await_count == 3


def test_detail_response_strips_debug_blocks():
    session = _FakeSession()
    svc, _ = _service(session, _FakeLLM())
    analysis = asyncio.run(svc.execute(company=_FakeCompany())).analysis
    analysis.user_id = 2
    analysis.created_at = None
    analysis.llm_analysis["_input_context"] = {"huge": "debug block"}
    analysis.llm_analysis["evidence"] = {"source_count": 1}
    db = AsyncMock()
    db.execute.side_effect = [result(analysis), result(_FakeCompany()),
                              SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))]
    response = asyncio.run(api.get_analysis(analysis.analysis_id, request(), db))
    # Debug/provenance blocks stay persisted on the row but never ship.
    assert all(not key.startswith("_") for key in response.analysis)
    assert "evidence" not in response.analysis
    assert "source_backed_claims" not in response.analysis
    assert "_input_context" in analysis.llm_analysis


def test_detail_passes_through_invalidating_conditions():
    session = _FakeSession()
    svc, _ = _service(session, _FakeLLM())
    analysis = asyncio.run(svc.execute(company=_FakeCompany())).analysis
    analysis.user_id = 2
    analysis.created_at = None
    analysis.llm_analysis["invalidating_conditions"] = [
        "Failure of the AI roadmap to materialize.",
    ]
    db = AsyncMock()
    db.execute.side_effect = [result(analysis), result(_FakeCompany()),
                              SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))]
    response = asyncio.run(api.get_analysis(analysis.analysis_id, request(), db))
    assert response.recommendation.invalidating_conditions == [
        "Failure of the AI roadmap to materialize.",
    ]


def test_repeated_cancel_never_deletes():
    row = SimpleNamespace(user_id=2, status="llm_analysis")
    db = AsyncMock()
    db.execute.return_value = result(row)
    for _ in range(2):
        response = asyncio.run(api.cancel_analysis("job", request(), db))
        assert response["status"] == "cancelled"
    db.delete.assert_not_awaited()
    assert db.commit.await_count == 1


def test_delete_active_job_requires_explicit_cancellation():
    db = AsyncMock()
    db.execute.return_value = result(SimpleNamespace(user_id=2, status="llm_analysis"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.delete_analysis("job", request(), db))
    assert exc.value.status_code == 409
    db.delete.assert_not_awaited()


def test_late_cancel_preserves_completed_result():
    db = AsyncMock()
    db.execute.return_value = result(SimpleNamespace(user_id=2, status="completed"))
    assert asyncio.run(api.cancel_analysis("job", request(), db))["status"] == "completed"
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("value", ["0.7", 0.7])
def test_company_confidence_normalized(value):
    from app.domains.stock.scoring.analysis_validator import AnalysisValidator
    output = dict(summary="s", market_interpretation="m", causes=[], bull_case=[],
                  bear_case=[], investment_thesis="t", confidence=value)
    AnalysisValidator.validate_company_analysis(output)
    assert output["confidence"] == 0.7
    assert isinstance(output["confidence"], float)


@pytest.mark.parametrize("value", [None, True, "bad", "nan", "inf", -1, 2])
def test_invalid_confidence_rejected(value):
    from app.domains.stock.scoring.analysis_validator import normalize_confidence, AnalysisValidationError
    with pytest.raises(AnalysisValidationError):
        normalize_confidence(value)


def test_framework_score_lookup_targets_exact_row():
    from app.domains.stock.services.company_analysis import _load_run_score
    db = AsyncMock()
    score = SimpleNamespace(id=101)
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: score))
    assert asyncio.run(_load_run_score(db, 7, 101)) is score
    statement = db.execute.call_args.args[0]
    parameters = statement.compile().params
    assert parameters == {"company_id_1": 7, "id_1": 101}
    assert "ORDER BY" not in str(statement)


def test_job_list_returns_totals_dates_and_permissions():
    from datetime import datetime, timezone
    own = SimpleNamespace(id=1, analysis_id="own", user_id=2, status="queued",
                          investment_score=None, risk_score=None, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    shared = SimpleNamespace(id=2, analysis_id="shared", user_id=None, status="completed",
                             investment_score=80, risk_score=20, created_at=own.created_at)
    db = AsyncMock()
    db.execute.side_effect = [SimpleNamespace(all=lambda: [(own, "AAPL"), (shared, "MSFT")]),
                              SimpleNamespace(all=lambda: [("queued", 3), ("completed", 27)])]
    response = asyncio.run(api.list_analysis_jobs(request(), limit=20, offset=0, db=db))
    assert response["total"] == 30
    assert response["status_counts"] == {"queued": 3, "completed": 27}
    assert response["jobs"][0]["can_manage"] is True
    assert response["jobs"][1]["can_manage"] is False
    assert response["jobs"][0]["created_at"] == "2026-01-01T00:00:00+00:00"


def test_framework_rejects_unsupported_inclusions_before_queueing(monkeypatch):
    from app.domains.stock import config
    monkeypatch.setattr(config, "get_stock_config", lambda: SimpleNamespace(ANALYSIS_ENGINE="framework"))
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.create_company_analysis(AnalysisRequest(ticker="AAPL", include_news=False), BackgroundTasks(), request(), db))
    assert exc.value.status_code == 422
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_request_settings_survive_analysis_completion():
    session = _FakeSession()
    options = {"ticker": "AAPL", "include_news": False}
    existing = SimpleNamespace(id=42, analysis_id="job", status="queued", llm_analysis={"_request": options})
    session.existing = existing
    svc, _ = _service(session, _FakeLLM())
    completed = asyncio.run(svc.execute(company=_FakeCompany(), existing=existing, include_news=False)).analysis
    assert completed.llm_analysis["_request"] == options


def test_failed_detail_exposes_recovery_metadata():
    session = _FakeSession()
    svc, _ = _service(session, _FakeLLM())
    analysis = asyncio.run(svc.execute(company=_FakeCompany())).analysis
    analysis.user_id = 2
    analysis.created_at = None
    analysis.status = "failed"
    analysis.llm_analysis = {"_failure_reason": "Retry processing.", "_request": {"ticker": "AAPL", "include_news": False}}
    db = AsyncMock()
    db.execute.side_effect = [result(analysis), result(_FakeCompany()),
                              SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))]
    response = asyncio.run(api.get_analysis(analysis.analysis_id, request(), db))
    assert response.failure_reason == "Retry processing."
    assert response.request_options["include_news"] is False
