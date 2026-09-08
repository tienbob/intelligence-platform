"""All-empty RAG retrieval must be degraded, not successful.

Regression for the zero-evidence run that reported
``stages["rag"] == "success"`` and kept full confidence: the stock RAG
adapter returns a bucket dict (``{"news": [], "sec_filing": [], ...}``) on
a structurally healthy retrieval, and that dict is truthy — so the
pipeline's ``if not result`` degraded branch never fired and
``RAG_DEGRADED_CONFIDENCE_CAP`` (0.85) was dead code for the exact state
it exists for.

Acceptance criteria:

    all buckets empty   -> stages["rag"] == "degraded" -> confidence <= 0.85
    any bucket non-empty -> normal RAG path (success)
"""

import asyncio

from app.intelligence.pipeline import IntelligencePipeline
from app.shared.entities import AnalysisRequest, EntityRef

EMPTY_BUCKETS = {
    "news": [],
    "sec_filing": [],
    "event": [],
    "analysis": [],
}


class _FakeRag:
    """Minimal stand-in for the stock RAG pipeline adapter."""

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    async def retrieve_context(self, query, **kwargs):
        if self._exc is not None:
            raise self._exc

        return self._result


def _pipeline(rag: _FakeRag) -> IntelligencePipeline:
    # _retrieve_context only touches self._rag; skipping __init__ avoids
    # wiring the real registry / entity-resolution services.
    pipeline = object.__new__(IntelligencePipeline)
    pipeline._rag = rag
    return pipeline


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        entity_ref=EntityRef(
            domain="stock",
            entity_type="company",
            entity_id="TSLA",
        ),
        analysis_type="company",
    )


def _retrieve(rag: _FakeRag):
    # _retrieve_context(domain, request) does not use the domain argument;
    # None keeps the unit test free of registry wiring.
    return asyncio.run(
        _pipeline(rag)._retrieve_context(None, _request())
    )


def test_all_empty_buckets_are_degraded():
    rag_context, status, issues = _retrieve(_FakeRag(result=EMPTY_BUCKETS))

    assert status == "degraded"
    assert issues == ["RAG returned no usable context"]
    # Buckets are preserved so stage details, the news-gap diagnostic, and
    # retrieval stats keep their shape.
    assert rag_context == EMPTY_BUCKETS


def test_any_populated_bucket_is_success():
    result = {**EMPTY_BUCKETS, "news": [{"id": "news_1"}]}

    rag_context, status, issues = _retrieve(_FakeRag(result=result))

    assert status == "success"
    assert issues == []
    assert rag_context is result


def test_none_result_is_degraded():
    _, status, _ = _retrieve(_FakeRag(result=None))

    assert status == "degraded"


def test_rag_exception_still_degrades():
    _, status, issues = _retrieve(
        _FakeRag(exc=RuntimeError("pgvector down"))
    )

    assert status == "degraded"
    assert issues and "pgvector down" in issues[0]


def test_has_retrievable_evidence_semantics():
    has_evidence = IntelligencePipeline._has_retrievable_evidence

    assert not has_evidence(EMPTY_BUCKETS)
    assert not has_evidence(None)
    assert not has_evidence({})
    assert has_evidence({"news": [{"id": "news_1"}]})


def test_degraded_rag_caps_final_confidence_at_0_85():
    assert (
        IntelligencePipeline._final_confidence(
            1.0,
            {},
            {"rag": "degraded"},
        )
        == 0.85
    )


def test_successful_rag_keeps_deterministic_score_confidence():
    assert (
        IntelligencePipeline._final_confidence(
            1.0,
            {},
            {"rag": "success"},
        )
        == 1.0
    )


def test_acceptance_zero_evidence_run_is_capped():
    # End-to-end acceptance: all buckets empty -> stage degraded ->
    # final confidence <= 0.85 even when the deterministic score is
    # perfectly confident.
    _, status, _ = _retrieve(_FakeRag(result=EMPTY_BUCKETS))

    confidence = IntelligencePipeline._final_confidence(
        1.0,
        {},
        {"rag": status},
    )

    assert status == "degraded"
    assert confidence <= 0.85


def test_unsupported_claims_cap_still_applies_below_rag_cap():
    llm_output = {"_validation": {"claims_unsupported": 2}}

    assert (
        IntelligencePipeline._final_confidence(
            1.0,
            llm_output,
            {"rag": "degraded"},
        )
        == 0.70
    )