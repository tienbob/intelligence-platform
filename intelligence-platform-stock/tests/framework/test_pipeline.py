"""
Framework tests: IntelligencePipeline lifecycle (Phase 9).

Runs the complete generic lifecycle against a fake domain module and
injected fake services (plan §9.1: tests inject fakes). Verifies:
  - stage order and data flow
  - entity resolution through the framework service
  - evidence built by the framework evidence core
  - validation + scoring strategy invocation
  - result envelope population
  - unknown-domain failure handling
  - domain neutrality of the pipeline source
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.pipeline import IntelligencePipeline  # noqa: E402
from app.shared.entities import (  # noqa: E402
    AnalysisRequest,
    EntityRef,
)


# ── Fakes ────────────────────────────────────────────────────────

class _FakeEntityResolution:
    def __init__(self):
        self.calls = []

    async def resolve(self, ref):
        self.calls.append(ref)
        if ref.entity_id == "nasdaq:aapl":
            return EntityRef(ref.domain, ref.entity_type, "AAPL")
        return ref


class _FetchProvider:
    async def fetch(self, entity_ref):
        return [
            {"metric": "pe", "value": 30.5},
            {"metric": "rsi", "value": 61.0},
        ]


class _NoFetchProvider:
    """Capability-style provider (no generic fetch) — must be skipped."""


class _FakeNormalizer:
    async def normalize(self, raw_data, entity_ref):
        return []


class _FakeContextBuilder:
    def __init__(self):
        self.built_with = None

    async def build(self, *, entity_ref, evidence, observations, rag_context, **kw):
        self.built_with = {
            "rag_keys": sorted(rag_context.keys()),
            "evidence_count": len(evidence),
        }
        from app.shared.entities import IntelligenceContext

        return IntelligenceContext(
            entity={"id": entity_ref.entity_id},
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
            domain_snapshots={},
        )


class _FakeLLM:
    def __init__(self):
        self.received_context = None
        self.last_kwargs = None

    async def analyze(self, system_prompt, context, analysis_type="", prompt_name="", **kw):
        self.received_context = context
        self.last_kwargs = kw
        return {
            "summary": "synthetic analysis",
            "insights": [{"text": "i1"}],
            "risks": ["r1"],
            "_meta": {"model": "fake-model", "tokens_used": 11},
        }


class _FakeScoringStrategy:
    def __init__(self):
        self.called_with = None

    async def score(self, entity_ref, context, llm_output):
        self.called_with = {"llm_summary": llm_output.get("summary")}
        return {
            "score": 77.5,
            "confidence": 0.9,
            "recommendation": "BUY",
            "components": {"fundamental": 80.0},
        }


class _FakeRAG:
    async def retrieve_context(self, query, **kwargs):
        return {"news": [{"id": 1}], "filings": [{"id": 2}]}


class _FakeDomain:
    name = "fake"
    version = "1.0"

    def __init__(self):
        self.builder = _FakeContextBuilder()
        self.strategy = _FakeScoringStrategy()

    def get_providers(self):
        return {"fetcher": _FetchProvider(), "capability": _NoFetchProvider()}

    def get_normalizers(self):
        return {"fetcher": _FakeNormalizer()}

    def get_context_builder(self):
        return self.builder

    def get_scoring_strategy(self):
        return self.strategy

    def get_prompts(self):
        class _P:
            def get(self, name, default=""):
                return default or "system prompt"

        return _P()

    def get_api_router(self):
        raise NotImplementedError

    def get_internal_router(self):
        raise NotImplementedError

    def get_intelligence_tasks(self):
        return []


class _FakeRegistry:
    def __init__(self, domains):
        self._domains = domains

    def get(self, name):
        return self._domains.get(name)


def _pipeline(domain, **overrides):
    er = overrides.get("entity_resolution") or _FakeEntityResolution()
    return IntelligencePipeline(
        registry=_FakeRegistry({"fake": domain}),
        entity_resolution=er,
        rag_service=overrides.get("rag"),
        llm_service=overrides.get("llm"),
    )


def _request():
    return AnalysisRequest(
        entity_ref=EntityRef("fake", "widget", "nasdaq:aapl"),
        analysis_type="comprehensive",
    )


# ── Tests ────────────────────────────────────────────────────────

def test_full_lifecycle_happy_path():
    domain = _FakeDomain()
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))

    assert result.status == "completed"
    assert result.entity_ref.entity_id == "AAPL"          # resolved
    assert result.score == 77.5
    assert result.confidence == 0.9
    assert result.recommendation == "BUY"
    assert result.summary == "synthetic analysis"
    # evidence built from fetched observations via framework core
    assert len(result.evidence) == 2
    assert result.evidence[0].source_type == "fetcher"
    assert result.metadata["domain"] == "fake"
    assert result.metadata["llm_model"] == "fake-model"


def test_entity_resolution_invoked_through_framework():
    er = _FakeEntityResolution()
    domain = _FakeDomain()
    pipe = IntelligencePipeline(
        registry=_FakeRegistry({"fake": domain}), entity_resolution=er
    )
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert er.calls, "entity resolution service was not consulted"
    assert er.calls[0].entity_id == "nasdaq:aapl"


def test_provider_without_fetch_is_skipped_not_fatal():
    pipe = _pipeline(_FakeDomain())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"


def test_unknown_domain_fails_gracefully():
    pipe = IntelligencePipeline(registry=_FakeRegistry({}))
    result = asyncio.run(
        pipe.run(AnalysisRequest(entity_ref=EntityRef("ghost", "x", "y")))
    )
    assert result.status == "failed"
    assert "ghost" in result.summary


def test_llm_receives_rag_and_snapshot_context():
    domain = _FakeDomain()
    llm = _FakeLLM()
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=llm)
    asyncio.run(pipe.run(_request()))
    ctx = llm.received_context
    assert set(ctx["rag_context"]) == {"news", "filings"}
    assert domain.builder.built_with["rag_keys"] == ["filings", "news"]
    assert domain.builder.built_with["evidence_count"] == 2


def test_scoring_strategy_receives_llm_output():
    domain = _FakeDomain()
    pipe = _pipeline(domain, llm=_FakeLLM())
    asyncio.run(pipe.run(_request()))
    assert domain.strategy.called_with["llm_summary"] == "synthetic analysis"


def test_pipeline_source_has_no_domain_branches():
    root = Path(__file__).resolve().parents[2]
    src = (root / "app" / "intelligence" / "pipeline.py").read_text()
    for bad in ('== "stock"', "== 'stock'", "if domain =="):
        assert bad not in src, f"domain-specific branch found: {bad}"


# ── Phase 10.3: stage observability ──────────────────────────────

def test_all_stages_recorded_on_success():
    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    stages = result.metadata["stages"]
    expected = [
        "entity_resolution", "ingestion", "normalization", "evidence",
        "rag", "context", "llm", "validation", "scoring",
    ]
    assert list(stages) == expected
    assert all(v == "success" for v in stages.values()), stages


def test_missing_llm_is_degraded_not_failed():
    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG())  # no llm
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    stages = result.metadata["stages"]
    assert stages["llm"] == "degraded"
    assert stages["scoring"] == "success"  # analysis still possible


def test_rag_skipped_when_service_absent():
    pipe = _pipeline(_FakeDomain())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert result.metadata["stages"]["rag"] == "skipped"


# ── Phase 10.4: failure semantics ────────────────────────────────

def test_scoring_failure_is_hard():
    class _BrokenStrategy:
        async def score(self, *a, **kw):
            raise RuntimeError("db exploded")

    domain = _FakeDomain()
    domain.strategy = _BrokenStrategy()
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    assert "scoring" in result.summary
    assert result.metadata["stages"]["scoring"].startswith("failed")


def test_context_failure_is_hard_and_records_stage():
    class _BrokenBuilder:
        async def build(self, **kw):
            raise ValueError("no snapshots")

    domain = _FakeDomain()
    domain.builder = _BrokenBuilder()
    pipe = _pipeline(domain)
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    assert "context" in result.summary
    stages = result.metadata["stages"]
    assert stages["context"].startswith("failed")
    # later stages never ran
    assert "llm" not in stages


def test_entity_resolution_failure_is_hard():
    class _BrokenER:
        async def resolve(self, ref):
            raise RuntimeError("resolver down")

    pipe = IntelligencePipeline(
        registry=_FakeRegistry({"fake": _FakeDomain()}),
        entity_resolution=_BrokenER(),
    )
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    assert "entity_resolution" in result.summary


# ── Phase 10.1/10.2: Stock factory vs minimal default ────────────

def test_stock_factory_builds_fully_wired_pipeline():
    from app.domains.stock.pipeline_factory import build_stock_pipeline

    pipe = build_stock_pipeline()
    assert type(pipe._rag).__name__ == "StockRAGPipelineAdapter"
    assert type(pipe._llm).__name__ == "LLMService"
    # framework defaults present
    assert pipe._entity_resolution is not None
    assert pipe._evidence_svc is not None
    assert pipe._validation is not None


def test_minimal_default_remains_dependency_free():
    pipe = IntelligencePipeline()
    assert pipe._llm is None and pipe._rag is None  # no Stock imports needed


# ── Gate 0: stage-status accuracy (V3 §17) ───────────────────────

class _FailingFetchProvider:
    async def fetch(self, entity_ref):
        raise RuntimeError("provider down")


def _domain_with_providers(providers, normalizers=None):
    domain = _FakeDomain()
    domain.get_providers = lambda: providers
    if normalizers is not None:
        domain.get_normalizers = lambda: normalizers
    return domain


def test_partial_provider_failure_reports_degraded_not_success():
    domain = _domain_with_providers(
        {"ok": _FetchProvider(), "bad": _FailingFetchProvider()}
    )
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert result.metadata["stages"]["ingestion"] == "degraded"
    assert result.metadata["stage_details"]["ingestion"] == ["bad"]
    # data from the healthy provider still flows through
    assert len(result.evidence) == 2


def test_total_provider_failure_is_hard():
    domain = _domain_with_providers(
        {"bad1": _FailingFetchProvider(), "bad2": _FailingFetchProvider()}
    )
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    assert "ingestion" in result.summary
    assert result.metadata["stages"]["ingestion"].startswith("failed")


def test_normalizer_failure_reports_degraded_and_preserves_raw_data():
    class _BrokenNormalizer:
        async def normalize(self, raw_data, entity_ref):
            raise ValueError("schema drift")

    domain = _domain_with_providers(
        {"fetcher": _FetchProvider()},
        normalizers={"fetcher": _BrokenNormalizer()},
    )
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert result.metadata["stages"]["normalization"] == "degraded"
    assert result.metadata["stage_details"]["normalization"] == ["fetcher"]
    # raw observations preserved → evidence still collected
    assert len(result.evidence) == 2


def test_worker_fed_ingestion_noop_still_reports_success():
    """No fetch-capable providers = expected worker-owned path, not degraded."""
    domain = _domain_with_providers({"capability": _NoFetchProvider()})
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert result.metadata["stages"]["ingestion"] == "success"


def test_pipeline_version_label_is_populated_from_versioning_module():
    from app.core.versioning import PIPELINE_VERSION

    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.metadata["pipeline_version"] == PIPELINE_VERSION
    assert result.metadata["domain_version"] == _FakeDomain.version


# ── Gate 1: reproducibility provenance (audit Finding 6) ─────────

def test_result_metadata_carries_full_llm_provenance():
    """Finding 6: prompt name/version, provider, temperature, max_tokens,
    analysis type must all be present on successful results."""

    class _MetaLLM(_FakeLLM):
        async def analyze(self, system_prompt, context, analysis_type="", prompt_name=""):
            return {
                "summary": "s",
                "insights": [],
                "risks": [],
                "_meta": {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "tokens_used": 321,
                    "prompt_name": "stock_company",
                    "prompt_version": "1.0",
                    "analysis_type": analysis_type,
                    "temperature": 0.2,
                    "max_tokens": 4096,
                },
            }

    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG(), llm=_MetaLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    md = result.metadata
    assert md["prompt_name"] == "stock_company"
    assert md["prompt_version"] == "1.0"
    assert md["llm_provider"] == "openai"
    assert md["llm_model"] == "gpt-4o"
    assert md["llm_temperature"] == 0.2
    assert md["llm_max_tokens"] == 4096
    assert md["llm_tokens"] == 321
    assert md["analysis_type"] == "comprehensive"


def test_failed_result_metadata_still_carries_provenance():
    """Finding 6: failure results must not drop domain/version/stages."""
    from app.core.versioning import PIPELINE_VERSION

    class _BrokenStrategy:
        async def score(self, *a, **kw):
            raise RuntimeError("boom")

    domain = _FakeDomain()
    domain.strategy = _BrokenStrategy()
    pipe = _pipeline(domain, rag=_FakeRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    md = result.metadata
    assert md["domain"] == "fake"
    assert md["pipeline_version"] == PIPELINE_VERSION
    assert "stages" in md and "scoring" in md["stages"]
    assert "stage_details" in md


def test_llm_crash_is_hard_failure_with_stage_attribution():
    """§17.3: an LLM exception when LLM is required aborts the run as
    ``failed`` — distinct from degraded/skipped."""

    class _CrashingLLM:
        async def analyze(self, *a, **kw):
            raise RuntimeError("provider 500")

    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG(), llm=_CrashingLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "failed"
    assert result.metadata["stages"]["llm"].startswith("failed")


def test_rag_configured_but_empty_is_degraded():
    """§17.4: RAG returning empty context degrades the run — distinct from
    skipped (service absent) and from hard failures."""

    class _EmptyRAG:
        async def retrieve_context(self, query, **kwargs):
            return {}

    pipe = _pipeline(_FakeDomain(), rag=_EmptyRAG(), llm=_FakeLLM())
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert result.metadata["stages"]["rag"] == "degraded"


# ── Gate 3: §32 evidence attribution through the generic pipeline ─

def test_pipeline_forwards_domain_evidence_attributor_to_llm():
    sentinel = object()

    class _AttrDomain(_FakeDomain):
        def get_evidence_attributor(self, context):
            assert context["rag_context"] is not None
            return sentinel

    llm = _FakeLLM()
    pipe = _pipeline(_AttrDomain(), rag=_FakeRAG(), llm=llm)
    result = asyncio.run(pipe.run(_request()))
    assert result.status == "completed"
    assert llm.last_kwargs.get("evidence_attributor") is sentinel


def test_pipeline_skips_attributor_when_domain_omits_it():
    llm = _FakeLLM()
    pipe = _pipeline(_FakeDomain(), rag=_FakeRAG(), llm=llm)
    asyncio.run(pipe.run(_request()))
    assert "evidence_attributor" not in (llm.last_kwargs or {})

