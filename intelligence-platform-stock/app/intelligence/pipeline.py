"""
Intelligence Pipeline — the central orchestration engine.

This is the MOST IMPORTANT component of the generalized platform.
It implements the domain-agnostic intelligence lifecycle (12 stages):

    Request → Domain Resolver → Ingestion → Normalization →
    Entity Resolution → Evidence Collection → RAG Retrieval →
    Context Builder → LLM → Structured Validation →
    Domain Scoring → Result

The pipeline knows HOW to run intelligence.
The domain knows WHAT intelligence means.

⚠️  INTEGRATION STATUS — READ BEFORE EDITING:

    Phase 9: this pipeline is now a **fully functional generic
    orchestrator** — injectable services with framework defaults,
    entity-resolution stage, evidence via the evidence core, validation,
    and optional-capability scoring (verified by
    tests/framework/test_pipeline.py).

    It is still NOT wired into the production analysis execution path.
    Nothing instantiates ``IntelligencePipeline`` in production and no
    production code calls ``run()``. Per plan §9.6, switch over only
    after the golden comparison passes:

        production path  → baseline_aapl.json
        pipeline.run()   → pipeline_aapl.json

    Production company analysis currently runs through::

        api/analysis.py / analysis_worker.py
            → InvestmentScoringEngine (scoring/investment_scoring.py)

    Do not assume changes here affect production analysis until the
    pipeline is explicitly integrated (future architecture task: decide
    whether it replaces, wraps, or orchestrates InvestmentScoringEngine).

    Related deliberate decisions already encoded in this file:
      * ``_ingest`` treats providers lacking ``fetch(entity_ref)`` as an
        expected no-op (worker-owned ingestion), not an error.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.core.versioning import PIPELINE_VERSION
from app.intelligence.contracts import DomainModule
from app.intelligence.registry import get_registry
from app.shared.entities import (
    AnalysisRequest,
    AnalysisResult,
    EntityRef,
    Evidence,
    IntelligenceContext,
    Observation,
)

logger = get_logger(__name__)


class StageFailure(RuntimeError):
    """A pipeline stage hard-failure (V3 §17.3).

    ``str(exc)`` carries only the detail so the generic handler can record
    ``stages[stage] = f"failed: {exc}"`` without a duplicated prefix; the
    offending stage name is kept on ``.stage``.
    """

    def __init__(self, stage: str, issues: list[str]):
        self.stage = stage
        super().__init__("; ".join(issues) or stage)


class IntelligencePipeline:
    """
    The central intelligence pipeline — domain-agnostic.

    Orchestrates the full lifecycle of an intelligence request:
    data ingestion → normalization → evidence → RAG → context → LLM → scoring → result.

    Usage:
        pipeline = IntelligencePipeline(llm_service, rag_service, embedding_service)
        result = await pipeline.run(AnalysisRequest(
            entity_ref=EntityRef(domain="stock", entity_type="company", entity_id="AAPL"),
        ))
    """

    def __init__(
        self,
        *,
        registry: Any = None,
        entity_resolution: Any = None,
        llm_service: Any = None,
        rag_service: Any = None,
        embedding_service: Any = None,
        evidence_service: Any = None,
        validation_service: Any = None,
    ):
        # Injectable dependencies (plan §9.1): production uses framework
        # defaults, tests inject fakes, future domains reuse everything.
        self._registry = registry or get_registry()
        # Entity resolution is a pure in-process service → safe default.
        if entity_resolution is None:
            from app.intelligence.entity_resolution import (
                get_entity_resolution_service,
            )
            entity_resolution = get_entity_resolution_service()
        self._entity_resolution = entity_resolution
        # Evidence + validation are likewise framework-internal → defaults.
        if evidence_service is None:
            from app.intelligence.evidence import EvidenceService
            evidence_service = EvidenceService()
        self._evidence_svc = evidence_service
        if validation_service is None:
            from app.intelligence.validation import ValidationService
            validation_service = ValidationService()
        self._validation = validation_service
        # LLM / RAG / embeddings require external configuration (API keys,
        # pgvector) → stay optional and degrade gracefully when absent.
        self._llm = llm_service
        self._rag = rag_service
        self._embeddings = embedding_service

    # ── Pipeline Steps ──────────────────────────────────────────

    async def run(self, request: AnalysisRequest) -> AnalysisResult:
        """
        Execute the full intelligence pipeline for a request.

        Returns an AnalysisResult with status, score, confidence, and insights.
        """
        domain_name = request.entity_ref.domain
        domain = self._registry.get(domain_name)

        if domain is None:
            return AnalysisResult(
                entity_ref=request.entity_ref,
                status="failed",
                summary=f"Domain '{domain_name}' not found or not enabled",
            )

        # Stage observability (plan §10.3) + failure semantics (§10.4):
        # every stage records success / degraded / skipped / failed; only
        # hard failures abort the run, degraded ones continue.
        stages: dict[str, Any] = {}
        stage_details: dict[str, list[str]] = {}
        current_stage = "entity_resolution"

        try:
            logger.info(
                "Pipeline: domain '%s' entity %s/%s",
                domain_name,
                request.entity_ref.entity_type,
                request.entity_ref.entity_id,
            )

            # ── Entity resolution (hard failure) ────────────────
            request.entity_ref = await self._resolve_entity(request.entity_ref)
            stages[current_stage] = "success"

            # ── Ingestion ───────────────────────────────────────
            # Provider exceptions never collapse to a silent "success":
            # partial failure degrades the run, total failure of every
            # attempted provider aborts it (V3 §17.2–§17.4).
            current_stage = "ingestion"
            observations, ingest_status, ingest_issues = await self._ingest(
                domain, request
            )
            if ingest_status == "failed":
                raise StageFailure("ingestion", ingest_issues)
            stages[current_stage] = ingest_status
            if ingest_issues:
                stage_details[current_stage] = ingest_issues

            # ── Normalization ───────────────────────────────────
            current_stage = "normalization"
            observations, norm_status, norm_issues = await self._normalize(
                domain, observations, request.entity_ref
            )
            stages[current_stage] = norm_status
            if norm_issues:
                stage_details[current_stage] = norm_issues

            # ── Evidence (framework evidence core) ──────────────
            current_stage = "evidence"
            evidence = await self._collect_evidence(
                domain, observations, request.entity_ref
            )
            stages[current_stage] = "success"

            # ── RAG retrieval (optional → degraded/skipped) ─────
            current_stage = "rag"
            rag_context = await self._retrieve_context(domain, request)
            stages[current_stage] = "success" if rag_context else (
                "degraded" if self._rag is not None else "skipped"
            )

            # ── Context construction (hard failure) ────────────
            current_stage = "context"
            context = await self._build_context(
                domain, request.entity_ref, evidence, observations, rag_context
            )
            stages[current_stage] = "success"

            # ── LLM analysis (missing service → degraded) ──────
            current_stage = "llm"
            if self._llm is None:
                llm_output = {
                    "summary": "LLM service not configured",
                    "insights": [],
                    "risks": [],
                }
                stages[current_stage] = "degraded"
            else:
                llm_output = await self._run_llm(domain, context, request)
                stages[current_stage] = "success"

            # ── Validation (hard failure on validator crash) ───
            current_stage = "validation"
            if self._validation is not None:
                llm_output = await self._validate_output(domain, llm_output, request)
                stages[current_stage] = "success"
            else:
                stages[current_stage] = "skipped"

            # ── Domain scoring (hard failure) ───────────────────
            current_stage = "scoring"
            score_result = await self._score(
                domain, request.entity_ref, context, llm_output
            )
            stages[current_stage] = "success"

            # Reproducibility provenance (V3 §18.2/§19; audit Finding 6):
            # surface the COMPLETE audit block produced by the LLM engine,
            # not just model/tokens, so every analysis is reproducible and
            # comparable in shadow production.
            llm_meta = llm_output.get("_meta", {})
            return AnalysisResult(
                entity_ref=request.entity_ref,
                status="completed",
                summary=llm_output.get("summary", ""),
                score=score_result.get("score"),
                confidence=score_result.get("confidence", 0.0),
                recommendation=score_result.get("recommendation", ""),
                evidence=evidence,
                insights=llm_output.get("insights", []),
                risks=llm_output.get("risks", []),
                metadata={
                    "domain": domain_name,
                    "domain_version": domain.version,
                    "analysis_type": request.analysis_type,
                    "pipeline_version": PIPELINE_VERSION,
                    "prompt_name": llm_meta.get("prompt_name"),
                    "prompt_version": llm_meta.get("prompt_version"),
                    "llm_provider": llm_meta.get("provider"),
                    "llm_model": llm_meta.get("model"),
                    "llm_temperature": llm_meta.get("temperature"),
                    "llm_max_tokens": llm_meta.get("max_tokens"),
                    "llm_tokens": llm_meta.get("tokens_used"),
                    "stages": stages,
                    "stage_details": stage_details,
                    # Domain snapshots ride along so ANY engine persisting a
                    # canonical Analysis row can populate snapshot columns
                    # without re-running the context stage (PLAN.md: one
                    # persisted contract across engines).
                    "domain_snapshots": dict(context.domain_snapshots),
                    "scoring_metadata": dict(score_result.get("metadata") or {}),
                },
                created_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            logger.exception(
                "Pipeline failed at stage '%s' for %s: %s",
                current_stage,
                request.entity_ref,
                exc,
            )
            stages[current_stage] = f"failed: {exc}"
            return AnalysisResult(
                entity_ref=request.entity_ref,
                status="failed",
                summary=f"Pipeline error at '{current_stage}': {exc}",
                metadata={
                    "domain": domain_name,
                    "pipeline_version": PIPELINE_VERSION,
                    "stages": stages,
                    "stage_details": stage_details,
                },
                created_at=datetime.now(timezone.utc),
            )

    # ── Step Implementations ────────────────────────────────────

    async def _resolve_entity(self, entity_ref: EntityRef) -> EntityRef:
        """Normalize the entity identifier through the framework service.

        Domains register their identifier semantics (e.g. Stock's ticker
        normalizer); the pipeline only knows the generic contract.
        Resolution failure is a HARD failure (plan §10.4) — it propagates.
        """
        resolved = await self._entity_resolution.resolve(entity_ref)
        if isinstance(resolved, EntityRef):
            return resolved
        return EntityRef(
            domain=entity_ref.domain,
            entity_type=entity_ref.entity_type,
            entity_id=resolved,
        )

    async def _ingest(
        self,
        domain: DomainModule,
        request: AnalysisRequest,
    ) -> tuple[list[Observation], str, list[str]]:
        """Ingest data from all domain providers.

        Architecture note (deliberate design decision): external provider
        fetching is *owned by domain ingestion workers*, which persist raw
        data to the database on their own schedules. This generic-pipeline
        stage only serves domains whose providers implement the lightweight
        ``Provider`` protocol (``fetch(entity_ref)``) for on-demand,
        request-time acquisition. When a domain's providers don't implement
        it — e.g. stock, where providers expose capability methods like
        ``get_quote(ticker)`` instead — this stage is intentionally a no-op:
        the pipeline then consumes persisted evidence and RAG context that
        the workers already produced. That avoids a second competing
        ingestion path (double API calls, rate-limit pressure, duplicated
        normalization) alongside the worker-owned one.

        Stage-status accuracy (Gate 0 / V3 §17): per-provider exceptions are
        isolated but never reported as a plain ``success``. Returns
        ``(observations, status, issues)`` where ``status`` is:

        * ``success``  — nothing attempted (worker-fed domain, expected) or
          every attempted provider succeeded;
        * ``degraded`` — some attempted providers raised; whatever was
          collected still flows downstream (§20: a provider limitation must
          not become a full pipeline failure);
        * ``failed``   — every attempted provider raised AND zero data was
          collected; continuing would analyse nothing while claiming health,
          so ``run()`` aborts via :class:`StageFailure` (§17.3).

        ``issues`` lists the failing provider names for result metadata.
        """
        providers = domain.get_providers()
        all_observations: list[Observation] = []
        attempted = 0
        failed_names: list[str] = []

        for name, provider in providers.items():
            # Distinguish "provider doesn't support generic ingestion"
            # (expected for worker-fed domains → skip quietly) from an
            # actual provider failure at fetch time (→ loud, full traceback).
            if not hasattr(provider, "fetch"):
                # Expected no-op, not an error: worker-fed domains own
                # ingestion on their own schedules (see module docstring).
                logger.debug(
                    "Provider '%s' does not implement the generic Provider "
                    "protocol (no fetch(entity_ref)); skipping provider "
                    "ingestion. Using persisted evidence/RAG instead.",
                    name,
                )
                continue

            attempted += 1
            try:
                raw_data = await provider.fetch(request.entity_ref)
                for item in raw_data:
                    all_observations.append(
                        Observation(
                            entity_ref=request.entity_ref,
                            observed_at=datetime.now(timezone.utc),
                            data=item,
                            source=name,
                        )
                    )
                logger.debug(
                    "Provider '%s' returned %d records", name, len(raw_data)
                )
            except Exception:
                failed_names.append(name)
                logger.exception(
                    "Provider '%s' failed during generic ingestion for %s/%s",
                    name,
                    request.entity_ref.domain,
                    request.entity_ref.entity_id,
                )

        if not failed_names:
            status = "success"
        elif len(failed_names) < attempted:
            status = "degraded"
        else:
            status = "failed"
        return all_observations, status, failed_names

    async def _normalize(
        self,
        domain: DomainModule,
        observations: list[Observation],
        entity_ref: EntityRef,
    ) -> tuple[list[Observation], str, list[str]]:
        """Normalize raw observations through domain normalizers.

        Normalization transforms known sources. Observations from sources
        that have no registered normalizer are preserved as-is — they are
        never silently discarded.

        Stage-status accuracy (Gate 0 / V3 §17): normalizer exceptions were
        previously swallowed into an unconditional ``success``; they now
        report ``degraded``. Normalization cannot hard-fail the run because
        raw observations are preserved below, so downstream stages always
        receive usable input (§20). Returns ``(observations, status,
        issues)``.
        """
        normalizers = domain.get_normalizers()
        if not normalizers:
            return observations, "success", []

        normalized: list[Observation] = []
        normalized_sources: set[str] = set()
        failed_names: list[str] = []

        for name, normalizer in normalizers.items():
            try:
                raw_data = [obs.data for obs in observations if obs.source == name]
                if raw_data:
                    result = await normalizer.normalize(raw_data, entity_ref)
                    normalized.extend(result)
                    normalized_sources.add(name)
            except Exception:
                failed_names.append(name)
                logger.exception("Normalizer '%s' failed", name)

        # Preserve observations from sources that had no normalizer
        for obs in observations:
            if obs.source not in normalized_sources:
                normalized.append(obs)

        status = "degraded" if failed_names else "success"
        return (normalized if normalized else observations), status, failed_names

    async def _collect_evidence(
        self,
        domain: DomainModule,
        observations: list[Observation],
        entity_ref: EntityRef,
    ) -> list[Evidence]:
        """Collect evidence from observations via the framework evidence core."""
        if not observations:
            return []
        return await self._evidence_svc.observations_to_evidence(observations)

    async def _retrieve_context(
        self, domain: DomainModule, request: AnalysisRequest
    ) -> dict[str, Any]:
        """Retrieve relevant context via RAG."""
        if self._rag is None:
            return {}

        try:
            query = f"Analysis of {request.entity_ref.entity_type} {request.entity_ref.entity_id}"
            return await self._rag.retrieve_context(
                query,
                domain=request.entity_ref.domain,
                entity_type=request.entity_ref.entity_type,
                entity_id=request.entity_ref.entity_id,
            )
        except Exception as exc:
            logger.warning("RAG retrieval failed: %s", exc)
            return {}

    async def _build_context(
        self,
        domain: DomainModule,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
    ) -> IntelligenceContext:
        """Build the structured intelligence context."""
        builder = domain.get_context_builder()
        return await builder.build(
            entity_ref=entity_ref,
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
        )

    async def _run_llm(
        self,
        domain: DomainModule,
        context: IntelligenceContext,
        request: AnalysisRequest,
    ) -> dict[str, Any]:
        """Run LLM analysis with domain-specific prompts."""
        if self._llm is None:
            return {"summary": "LLM service not configured", "confidence": 0.0}

        prompts = domain.get_prompts()
        system_prompt = prompts.get(
            request.analysis_type,
            prompts.get("default", "You are an expert analyst. Provide structured analysis."),
        )

        # Build the context dict for the LLM
        context_dict = {
            "entity": context.entity,
            "observations": [
                {"source": obs.source, "data": obs.data} for obs in context.observations
            ],
            "evidence": [
                {
                    "source_type": e.source_type,
                    "source_name": e.source_name,
                    "metric": e.metric,
                    "value": e.value,
                    "period": e.period,
                }
                for e in context.evidence
            ],
            "rag_context": context.rag_context,
            **context.domain_snapshots,
        }

        llm_kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "context": context_dict,
            "analysis_type": request.analysis_type,
            "prompt_name": f"{domain.name}_{request.analysis_type}",
        }
        # Optional §32 evidence attribution: the domain may expose a factory
        # that binds claim→source attribution to this run's RAG context. The
        # framework stays generic (it never imports domain code); it merely
        # hands the domain-provided attributor through to the domain's own
        # LLM service, so framework-path analyses keep source-attributed
        # claims exactly like the legacy/framework_path twins.
        attributor_factory = getattr(domain, "get_evidence_attributor", None)
        attributor = None
        if callable(attributor_factory):
            attributor = attributor_factory(context_dict)
            # Inject the list of valid source IDs into the LLM context so the
            # model can cite them in its structured output (§32). Only done
            # when the attributor exposes its registry (the generic Evidence-
            # Attributor contract); opaque attributors are passed through.
            registry = getattr(attributor, "source_registry", None)
            if registry is not None:
                context_dict["available_evidence_ids"] = sorted(registry.keys())
                # context_dict is already referenced by
                # llm_kwargs["context"], so the injected IDs are visible
                # to the LLM call below.
            llm_kwargs["evidence_attributor"] = attributor
        return await self._llm.analyze(**llm_kwargs)

    async def _validate_output(
        self,
        domain: DomainModule,
        llm_output: dict[str, Any],
        request: AnalysisRequest,
    ) -> dict[str, Any]:
        """Validate LLM structured output (hard failure on validator crash)."""
        if self._validation is None:
            return llm_output
        return await self._validation.validate(
            llm_output, domain.name, request.analysis_type
        )

    async def _score(
        self,
        domain: DomainModule,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute domain-specific score.

        Scoring is an optional capability. Domains that do not need a numeric
        score (e.g. legal document analysis) may return ``None`` from
        ``get_scoring_strategy()``. The pipeline handles this gracefully.
        """
        try:
            strategy = domain.get_scoring_strategy()
        except Exception:
            # Strategy *construction* problems degrade; scoring itself is hard.
            logger.exception("Scoring strategy unavailable for %s", domain.name)
            return {
                "score": None,
                "confidence": 0.0,
                "recommendation": "unavailable",
                "components": {},
            }
        if strategy is None:
            return {
                "score": None,
                "confidence": 0.0,
                "recommendation": None,
                "components": {},
            }
        # Scoring execution failures are hard failures (plan §10.4):
        # they propagate so the run aborts with the failing stage recorded.
        return await strategy.score(entity_ref, context, llm_output)
