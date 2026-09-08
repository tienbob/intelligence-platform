"""
Intelligence Pipeline — the central orchestration engine.

This is the MOST IMPORTANT component of the generalized platform.

It implements the domain-agnostic intelligence lifecycle:

    Request → Domain Resolver → Ingestion → Normalization →
    Entity Resolution → Evidence Collection → RAG Retrieval →
    Context Builder → LLM → Structured Validation →
    Domain Scoring → Result

The pipeline knows HOW to run intelligence.

The domain knows WHAT intelligence means.

Integrity invariants
--------------------
1. Deterministic scoring remains authoritative.
2. LLM output never becomes canonical scoring input.
3. Evidence-bearing claims must resolve to registered evidence or a
   domain-provided canonical source resolver.
4. Unsupported claims are explicitly surfaced and cannot be presented as
   verified/source-backed claims.
5. RAG degradation is observable through stage details.
6. Final confidence is bounded when factual/evidence integrity is degraded.
7. The original LLM output is retained for auditability, while verified
   structured claim collections exclude unsupported claims.

Integration status
------------------
Gates 5.2/6 (docs/PLAN.md): this pipeline is the production analysis engine
for both entry points:

    api/analysis.py / workers/analysis_worker.py
        → services/company_analysis.execute_company_analysis()
        → build_stock_pipeline()
        → IntelligencePipeline.run()

Domain providers implement the generic ``fetch(entity_ref)`` protocol where
appropriate. Worker-owned stock providers may intentionally omit ``fetch``;
in that case persisted observations/evidence/RAG are consumed without a
second competing ingestion path.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

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
    """A pipeline stage hard-failure (V3 §17.3)."""

    def __init__(self, stage: str, issues: list[str]):
        self.stage = stage
        super().__init__("; ".join(issues) or stage)


class IntelligencePipeline:
    """
    The central intelligence pipeline — domain-agnostic.

    Orchestrates:

        ingestion → normalization → evidence → RAG → context →
        LLM → validation → scoring → result

    Usage:

        pipeline = IntelligencePipeline(
            llm_service=llm_service,
            rag_service=rag_service,
        )

        result = await pipeline.run(
            AnalysisRequest(
                entity_ref=EntityRef(
                    domain="stock",
                    entity_type="company",
                    entity_id="AAPL",
                ),
            )
        )
    """

    # Confidence integrity policy.
    #
    # These are deliberately conservative ceilings applied to the final
    # analysis confidence when the analysis contains unresolved factual claims
    # or a degraded evidence/retrieval state.
    UNSUPPORTED_CLAIM_CONFIDENCE_CAP = 0.70
    RAG_DEGRADED_CONFIDENCE_CAP = 0.85

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
        self._registry = registry or get_registry()

        if entity_resolution is None:
            from app.intelligence.entity_resolution import (
                get_entity_resolution_service,
            )

            entity_resolution = get_entity_resolution_service()

        self._entity_resolution = entity_resolution

        if evidence_service is None:
            from app.intelligence.evidence import EvidenceService

            evidence_service = EvidenceService()

        self._evidence_svc = evidence_service

        if validation_service is None:
            from app.intelligence.validation import ValidationService

            validation_service = ValidationService()

        self._validation = validation_service

        # Kept for dependency injection compatibility. Embedding is normally
        # owned by the RAG/worker layer rather than request-time execution.
        self._llm = llm_service
        self._rag = rag_service
        self._embeddings = embedding_service

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def run(self, request: AnalysisRequest) -> AnalysisResult:
        """Execute the full intelligence pipeline."""
        domain_name = request.entity_ref.domain
        domain = self._registry.get(domain_name)

        if domain is None:
            return AnalysisResult(
                entity_ref=request.entity_ref,
                status="failed",
                summary=f"Domain '{domain_name}' not found or not enabled",
            )

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

            # ----------------------------------------------------------
            # Entity resolution
            # ----------------------------------------------------------
            request.entity_ref = await self._resolve_entity(
                request.entity_ref
            )
            stages[current_stage] = "success"

            # ----------------------------------------------------------
            # Ingestion
            # ----------------------------------------------------------
            current_stage = "ingestion"

            observations, ingest_status, ingest_issues = await self._ingest(
                domain,
                request,
            )

            if ingest_status == "failed":
                raise StageFailure("ingestion", ingest_issues)

            stages[current_stage] = ingest_status

            if ingest_issues:
                stage_details[current_stage] = ingest_issues

            # ----------------------------------------------------------
            # Normalization
            # ----------------------------------------------------------
            current_stage = "normalization"

            observations, norm_status, norm_issues = await self._normalize(
                domain,
                observations,
                request.entity_ref,
            )

            stages[current_stage] = norm_status

            if norm_issues:
                stage_details[current_stage] = norm_issues

            # ----------------------------------------------------------
            # Evidence
            # ----------------------------------------------------------
            current_stage = "evidence"

            evidence = await self._collect_evidence(
                domain,
                observations,
                request.entity_ref,
            )

            stages[current_stage] = "success"

            if not evidence and observations:
                stage_details[current_stage] = [
                    "No framework evidence records were produced from observations"
                ]
                stages[current_stage] = "degraded"

            # ----------------------------------------------------------
            # RAG
            # ----------------------------------------------------------
            current_stage = "rag"

            rag_context, rag_status, rag_issues = await self._retrieve_context(
                domain,
                request,
            )

            stages[current_stage] = rag_status

            if rag_issues:
                stage_details[current_stage] = rag_issues

            # ----------------------------------------------------------
            # Context
            # ----------------------------------------------------------
            current_stage = "context"

            context = await self._build_context(
                domain,
                request.entity_ref,
                evidence,
                observations,
                rag_context,
            )

            stages[current_stage] = "success"

            # ----------------------------------------------------------
            # LLM
            # ----------------------------------------------------------
            current_stage = "llm"

            if self._llm is None:
                llm_output = {
                    "summary": "LLM service not configured",
                    "insights": [],
                    "risks": [],
                    "_validation": {
                        "status": "llm_unavailable",
                    },
                }
                stages[current_stage] = "degraded"
                stage_details[current_stage] = [
                    "LLM service is not configured"
                ]
            else:
                llm_output = await self._run_llm(
                    domain,
                    context,
                    request,
                )
                stages[current_stage] = "success"

            # ----------------------------------------------------------
            # Structured validation
            # ----------------------------------------------------------
            current_stage = "validation"

            if self._validation is not None:
                llm_output = await self._validate_output(
                    domain,
                    llm_output,
                    request,
                )
                stages[current_stage] = "success"
            else:
                stages[current_stage] = "skipped"

            # ----------------------------------------------------------
            # Scoring
            # ----------------------------------------------------------
            current_stage = "scoring"

            # IMPORTANT:
            # _score receives the validated output for interface compatibility,
            # but the domain scoring contract must use canonical context values
            # as its deterministic source of truth. This pipeline never injects
            # unverified LLM-derived numeric facts into context.
            score_result = await self._score(
                domain,
                request.entity_ref,
                context,
                llm_output,
            )

            stages[current_stage] = "success"

            # ----------------------------------------------------------
            # Final confidence
            # ----------------------------------------------------------
            final_confidence = self._final_confidence(
                score_result.get("confidence", 0.0),
                llm_output,
                stages,
            )

            # ----------------------------------------------------------
            # Audit metadata
            # ----------------------------------------------------------
            llm_meta = llm_output.get("_meta", {})
            validation_meta = llm_output.get("_validation", {})

            metadata = {
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

                # Complete raw/auditable LLM output.
                "llm_output": llm_output,

                # Validation metadata made explicit for API consumers.
                "validation": validation_meta,

                # RAG/evidence audit surface.
                "rag_context": dict(context.rag_context),
                "evidence": [
                    self._serialize_evidence_item(item)
                    for item in evidence
                ],

                # Stage observability.
                "stages": stages,
                "stage_details": stage_details,

                # Canonical domain snapshots.
                "domain_snapshots": dict(context.domain_snapshots),

                # Preserve source-backed claims for auditability.
                "source_backed_claims": llm_output.get(
                    "source_backed_claims",
                    [],
                ),

                # Structured validation is the authoritative status for
                # factual claim integrity.
                "claim_validation": llm_output.get(
                    "claim_validation",
                    [],
                ),

                "llm_evidence": llm_output.get(
                    "evidence",
                    {},
                ),

                # Distinguish score confidence from final analysis confidence.
                "score_confidence": score_result.get(
                    "confidence",
                    0.0,
                ),
                "analysis_confidence": final_confidence,
            }

            return AnalysisResult(
                entity_ref=request.entity_ref,
                status="completed",
                summary=llm_output.get("summary", ""),
                score=score_result.get("score"),
                confidence=final_confidence,
                recommendation=score_result.get(
                    "recommendation",
                    "",
                ),
                evidence=evidence,
                insights=self._verified_structured_items(
                    llm_output.get("insights", []),
                ),
                risks=self._verified_structured_items(
                    llm_output.get("risks", []),
                ),
                metadata=metadata,
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
                summary=(
                    f"Pipeline error at '{current_stage}': {exc}"
                ),
                metadata={
                    "domain": domain_name,
                    "pipeline_version": PIPELINE_VERSION,
                    "stages": stages,
                    "stage_details": stage_details,
                },
                created_at=datetime.now(timezone.utc),
            )

    # ------------------------------------------------------------------
    # Entity resolution
    # ------------------------------------------------------------------

    async def _resolve_entity(
        self,
        entity_ref: EntityRef,
    ) -> EntityRef:
        """Normalize the entity identifier through the framework service."""
        resolved = await self._entity_resolution.resolve(entity_ref)

        if isinstance(resolved, EntityRef):
            return resolved

        return EntityRef(
            domain=entity_ref.domain,
            entity_type=entity_ref.entity_type,
            entity_id=resolved,
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def _ingest(
        self,
        domain: DomainModule,
        request: AnalysisRequest,
    ) -> tuple[list[Observation], str, list[str]]:
        """
        Ingest request-time observations where providers support fetch().

        Worker-fed providers without fetch() are intentionally skipped.
        """
        providers = domain.get_providers()

        all_observations: list[Observation] = []
        attempted = 0
        failed_names: list[str] = []

        for name, provider in providers.items():
            if not hasattr(provider, "fetch"):
                logger.debug(
                    "Provider '%s' does not implement fetch(entity_ref); "
                    "skipping request-time ingestion.",
                    name,
                )
                continue

            attempted += 1

            try:
                raw_data = await provider.fetch(request.entity_ref)

                if raw_data is None:
                    logger.debug(
                        "Provider '%s' returned no data",
                        name,
                    )
                    continue

                for item in raw_data:
                    if (
                        isinstance(item, dict)
                        and "kind" in item
                        and "data" in item
                    ):
                        all_observations.append(
                            Observation(
                                entity_ref=request.entity_ref,
                                observed_at=datetime.now(timezone.utc),
                                data=item["data"],
                                source=name,
                                kind=item["kind"],
                            )
                        )
                    else:
                        all_observations.append(
                            Observation(
                                entity_ref=request.entity_ref,
                                observed_at=datetime.now(timezone.utc),
                                data=item,
                                source=name,
                                kind="",
                            )
                        )

                logger.debug(
                    "Provider '%s' returned %d records",
                    name,
                    len(raw_data),
                )

            except Exception:
                failed_names.append(name)

                logger.exception(
                    "Provider '%s' failed during generic ingestion for "
                    "%s/%s",
                    name,
                    request.entity_ref.domain,
                    request.entity_ref.entity_id,
                )

        if not failed_names:
            status = "success"
        elif attempted == 0:
            status = "success"
        elif len(failed_names) < attempted:
            status = "degraded"
        else:
            status = "failed"

        return all_observations, status, failed_names

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    async def _normalize(
        self,
        domain: DomainModule,
        observations: list[Observation],
        entity_ref: EntityRef,
    ) -> tuple[list[Observation], str, list[str]]:
        """
        Normalize raw observations through domain normalizers.

        Unhandled sources remain preserved. Normalizer failure degrades the
        stage instead of silently becoming success.
        """
        normalizers = domain.get_normalizers()

        if not normalizers:
            return observations, "success", []

        normalized: list[Observation] = []
        normalized_sources: set[str] = set()
        failed_names: list[str] = []

        for name, normalizer in normalizers.items():
            try:
                raw_data = [
                    obs.data
                    for obs in observations
                    if obs.source == name
                ]

                if not raw_data:
                    continue

                result = await normalizer.normalize(
                    raw_data,
                    entity_ref,
                )

                normalized.extend(result)
                normalized_sources.add(name)

            except Exception:
                failed_names.append(name)

                logger.exception(
                    "Normalizer '%s' failed",
                    name,
                )

        # Preserve observations from sources without a successful normalizer.
        for obs in observations:
            if obs.source not in normalized_sources:
                normalized.append(obs)

        status = "degraded" if failed_names else "success"

        return (
            normalized if normalized else observations,
            status,
            failed_names,
        )

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    async def _collect_evidence(
        self,
        domain: DomainModule,
        observations: list[Observation],
        entity_ref: EntityRef,
    ) -> list[Evidence]:
        """
        Convert normalized observations into framework evidence.

        Canonical financial source-block resolution remains a domain-specific
        capability and is intentionally not faked here.
        """
        if not observations:
            return []

        evidence = await self._evidence_svc.observations_to_evidence(
            observations
        )

        return [
            item
            for item in evidence
            if self._evidence_matches_entity(
                item,
                entity_ref,
            )
        ]

    @staticmethod
    def _evidence_matches_entity(
        evidence: Evidence,
        entity_ref: EntityRef,
    ) -> bool:
        """
        Apply a defensive company/entity boundary when evidence carries it.

        Evidence implementations differ between domains, so fields are read
        defensively. Missing entity metadata does not reject otherwise valid
        generic evidence.
        """
        requested_id = str(entity_ref.entity_id).upper()

        evidence_entity_ref = getattr(
            evidence,
            "entity_ref",
            None,
        )

        if evidence_entity_ref is not None:
            evidence_id = getattr(
                evidence_entity_ref,
                "entity_id",
                None,
            )

            if (
                evidence_id is not None
                and str(evidence_id).upper() != requested_id
            ):
                return False

        evidence_entity_id = getattr(
            evidence,
            "entity_id",
            None,
        )

        if (
            evidence_entity_id is not None
            and str(evidence_entity_id).upper() != requested_id
        ):
            return False

        return True

    @staticmethod
    def _serialize_evidence_item(
        evidence: Evidence,
    ) -> dict[str, Any]:
        """Serialize evidence without assuming optional fields exist."""
        result = {
            "source_type": getattr(
                evidence,
                "source_type",
                None,
            ),
            "source_name": getattr(
                evidence,
                "source_name",
                None,
            ),
            "metric": getattr(
                evidence,
                "metric",
                None,
            ),
            "value": getattr(
                evidence,
                "value",
                None,
            ),
            "period": getattr(
                evidence,
                "period",
                None,
            ),
        }

        entity_type = getattr(
            evidence,
            "entity_type",
            None,
        )
        entity_id = getattr(
            evidence,
            "entity_id",
            None,
        )

        if entity_type is not None:
            result["entity_type"] = entity_type

        if entity_id is not None:
            result["entity_id"] = entity_id

        return result

    # ------------------------------------------------------------------
    # RAG
    # ------------------------------------------------------------------

    @staticmethod
    def _has_retrievable_evidence(result: Any) -> bool:
        """
        Return True when at least one RAG bucket contains documents.

        An adapter can succeed structurally yet return every bucket empty
        — that outcome produced zero usable evidence and must be treated
        as degraded, not as success. An empty bucket dict is truthy, which
        previously let a zero-evidence run report
        ``stages["rag"] == "success"`` and keep full confidence.
        """
        if not isinstance(result, dict):
            return False

        return any(
            bool(bucket)
            for bucket in result.values()
        )

    async def _retrieve_context(
        self,
        domain: DomainModule,
        request: AnalysisRequest,
    ) -> tuple[dict[str, Any], str, list[str]]:
        """
        Retrieve RAG context and preserve failure diagnostics.
        """
        if self._rag is None:
            return {}, "skipped", []

        try:
            query = (
                f"Analysis of "
                f"{request.entity_ref.entity_type} "
                f"{request.entity_ref.entity_id}"
            )

            result = await self._rag.retrieve_context(
                query,
                domain=request.entity_ref.domain,
                entity_type=request.entity_ref.entity_type,
                entity_id=request.entity_ref.entity_id,
            )

            rag_context = result if isinstance(result, dict) else {}

            # Structurally successful retrieval with every bucket empty
            # produced zero usable evidence: surface it as degraded so
            # RAG_DEGRADED_CONFIDENCE_CAP applies. The bucket dict is still
            # returned so stage details, the news-gap diagnostic, and
            # retrieval stats keep their shape.
            if not self._has_retrievable_evidence(rag_context):
                return (
                    rag_context,
                    "degraded",
                    ["RAG returned no usable context"],
                )

            return rag_context, "success", []

        except Exception as exc:
            logger.warning(
                "RAG retrieval failed for %s/%s: %s",
                request.entity_ref.domain,
                request.entity_ref.entity_id,
                exc,
            )

            return (
                {},
                "degraded",
                [f"RAG retrieval failed: {exc}"],
            )

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------

    async def _build_context(
        self,
        domain: DomainModule,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
    ) -> IntelligenceContext:
        """Build the domain-specific structured intelligence context."""
        builder = domain.get_context_builder()

        return await builder.build(
            entity_ref=entity_ref,
            evidence=evidence,
            observations=observations,
            rag_context=rag_context,
        )

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    async def _run_llm(
        self,
        domain: DomainModule,
        context: IntelligenceContext,
        request: AnalysisRequest,
    ) -> dict[str, Any]:
        """Run LLM analysis and perform preliminary evidence attribution."""
        if self._llm is None:
            return {
                "summary": "LLM service not configured",
                "confidence": 0.0,
            }

        prompts = domain.get_prompts()

        system_prompt = prompts.get(
            request.analysis_type,
            prompts.get(
                "default",
                "You are an expert analyst. Provide structured analysis.",
            ),
        )

        context_dict = {
            "entity": context.entity,
            "observations": [
                {
                    "source": obs.source,
                    "kind": obs.kind,
                    "data": obs.data,
                }
                for obs in context.observations
            ],
            "evidence": [
                self._serialize_evidence_item(item)
                for item in context.evidence
            ],
            "rag_context": context.rag_context,
            **context.domain_snapshots,
        }

        llm_kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "context": context_dict,
            "analysis_type": request.analysis_type,
            "prompt_name": (
                f"{domain.name}_{request.analysis_type}"
            ),
        }

        # --------------------------------------------------------------
        # Domain evidence attributor
        # --------------------------------------------------------------
        attributor_factory = getattr(
            domain,
            "get_evidence_attributor",
            None,
        )

        attributor = None

        if callable(attributor_factory):
            attributor = attributor_factory(context_dict)

            registry = getattr(
                attributor,
                "source_registry",
                None,
            )

            if isinstance(registry, dict):
                context_dict["available_evidence_ids"] = sorted(
                    str(key)
                    for key in registry.keys()
                )

            llm_kwargs["evidence_attributor"] = attributor

        output = await self._llm.analyze(**llm_kwargs)

        if not isinstance(output, dict):
            raise TypeError(
                "LLM service returned a non-dict structured output"
            )

        # --------------------------------------------------------------
        # Claim/evidence validation
        # --------------------------------------------------------------
        if attributor is not None:
            validator = getattr(
                attributor,
                "validate_claim_evidence",
                None,
            )

            resolver = getattr(
                attributor,
                "resolve_source_block",
                None,
            )

            if callable(validator):
                validations: list[dict[str, Any]] = []

                for field in (
                    "causes",
                    "source_backed_claims",
                ):
                    claims = output.get(field, [])

                    if not isinstance(claims, list):
                        continue

                    for claim in claims:
                        if not isinstance(claim, dict):
                            continue

                        evidence_ids = claim.get(
                            "evidence_ids",
                            [],
                        )

                        if not isinstance(evidence_ids, list):
                            evidence_ids = []

                        source = claim.get("source")

                        valid = False
                        validation_mode = "none"

                        # 1. Explicit evidence IDs.
                        try:
                            valid = bool(
                                await self._maybe_await(
                                    validator,
                                    claim,
                                )
                            )
                        except Exception as exc:
                            logger.warning(
                                "Evidence validator failed for %s: %s",
                                field,
                                exc,
                            )
                            valid = False

                        if valid:
                            validation_mode = "evidence_ids"

                        # 2. Canonical source block fallback.
                        #
                        # The source block is NEVER considered proof merely
                        # because it exists. It must resolve against the
                        # domain's canonical source resolver.
                        if (
                            not valid
                            and field != "causes"
                            and isinstance(source, dict)
                            and source
                            and callable(resolver)
                        ):
                            try:
                                resolved = await self._maybe_await(
                                    resolver,
                                    source,
                                )
                                valid = bool(resolved)

                                if valid:
                                    validation_mode = (
                                        "canonical_source"
                                    )
                            except Exception as exc:
                                logger.warning(
                                    "Source-block resolver failed for "
                                    "%s: %s",
                                    field,
                                    exc,
                                )
                                valid = False

                        has_candidates = bool(evidence_ids) or (
                            field != "causes"
                            and isinstance(source, dict)
                            and bool(source)
                        )

                        if valid:
                            status = "supported"
                            evidence_status = "available"
                        else:
                            status = "unsupported"

                            if has_candidates:
                                evidence_status = "insufficient"
                            else:
                                evidence_status = "unavailable"

                        claim_text = (
                            claim.get("cause")
                            or claim.get("claim")
                            or ""
                        )

                        validations.append(
                            {
                                "claim": claim_text,
                                "status": status,
                                "evidence_status": evidence_status,
                                "evidence_ids": evidence_ids,
                                "validation_mode": validation_mode,
                            }
                        )

                output = {
                    **output,
                    "claim_validation": validations,
                }

                # Preserve only verified source-backed claims in the
                # dedicated verified collection. Unsupported candidates remain
                # in the raw LLM output for auditability, but are not exposed
                # through this verified field.
                validated_source_claims = []

                for claim in output.get(
                    "source_backed_claims",
                    [],
                ):
                    if not isinstance(claim, dict):
                        continue

                    matching = next(
                        (
                            item
                            for item in validations
                            if item.get("claim")
                            == (
                                claim.get("claim")
                                or claim.get("cause")
                                or ""
                            )
                        ),
                        None,
                    )

                    if (
                        matching is not None
                        and matching.get("status") == "supported"
                    ):
                        validated_source_claims.append(claim)

                output["verified_source_backed_claims"] = (
                    validated_source_claims
                )

        return output

    # ------------------------------------------------------------------
    # Output validation
    # ------------------------------------------------------------------

    async def _validate_output(
        self,
        domain: DomainModule,
        llm_output: dict[str, Any],
        request: AnalysisRequest,
    ) -> dict[str, Any]:
        """
        Validate structured LLM output.

        Unsupported/conflicting claims are surfaced explicitly. Raw LLM output
        is retained for auditability, while verified source-backed collections
        exclude unsupported claims.

        The validator does not mutate deterministic scoring inputs.
        """
        if self._validation is None:
            return llm_output

        result = await self._validation.validate(
            llm_output,
            domain.name,
            request.analysis_type,
        )

        if not isinstance(result, dict):
            raise TypeError(
                "ValidationService returned a non-dict result"
            )

        validations = llm_output.get(
            "claim_validation",
            [],
        )

        if not isinstance(validations, list):
            validations = []

        unsupported = [
            item
            for item in validations
            if isinstance(item, dict)
            and item.get("status") != "supported"
        ]

        validation_meta = result.get("_validation")

        if not isinstance(validation_meta, dict):
            validation_meta = {}

        # Preserve any stronger validation status already produced by the
        # domain validator, but never allow unsupported claims to result in
        # an unconditional "valid".
        existing_status = validation_meta.get(
            "status",
            "valid",
        )

        if unsupported:
            status = "valid_with_evidence_issues"
        else:
            status = existing_status

        result["_validation"] = {
            **validation_meta,
            "status": status,
            "claim_validation_status": (
                "has_unsupported_claims"
                if unsupported
                else "all_supported"
            ),
            "claims_analyzed": len(validations),
            "claims_unsupported": len(unsupported),
            "claims_supported": (
                len(validations) - len(unsupported)
            ),
        }

        # Do not expose unsupported source-backed claims as verified.
        validated_source_claims = []

        for claim in result.get(
            "source_backed_claims",
            result.get(
                "verified_source_backed_claims",
                [],
            ),
        ):
            if not isinstance(claim, dict):
                continue

            claim_text = (
                claim.get("claim")
                or claim.get("cause")
                or ""
            )

            claim_status = next(
                (
                    item.get("status")
                    for item in validations
                    if (
                        isinstance(item, dict)
                        and item.get("claim") == claim_text
                    )
                ),
                "supported",
            )

            if claim_status == "supported":
                validated_source_claims.append(claim)

        result["verified_source_backed_claims"] = (
            validated_source_claims
        )

        # Keep explicit diagnostics for downstream UIs.
        result["claim_validation"] = validations

        return result

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    @classmethod
    def _final_confidence(
        cls,
        score_confidence: Any,
        llm_output: dict[str, Any],
        stages: dict[str, Any],
    ) -> float:
        """
        Produce final analysis confidence from deterministic score confidence
        plus integrity state.

        Confidence is bounded downward by evidence/validation problems rather
        than allowing a perfect deterministic score confidence to imply that
        the whole analysis is perfectly trustworthy.
        """
        try:
            confidence = float(score_confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))

        validation_meta = llm_output.get(
            "_validation",
            {},
        )

        if not isinstance(validation_meta, dict):
            validation_meta = {}

        claims_unsupported = validation_meta.get(
            "claims_unsupported",
            0,
        )

        try:
            claims_unsupported = int(claims_unsupported or 0)
        except (TypeError, ValueError):
            claims_unsupported = 0

        if claims_unsupported > 0:
            confidence = min(
                confidence,
                cls.UNSUPPORTED_CLAIM_CONFIDENCE_CAP,
            )

        if stages.get("rag") == "degraded":
            confidence = min(
                confidence,
                cls.RAG_DEGRADED_CONFIDENCE_CAP,
            )

        return round(confidence, 4)

    # ------------------------------------------------------------------
    # Structured-output safety
    # ------------------------------------------------------------------

    @staticmethod
    def _verified_structured_items(
        items: Any,
    ) -> list[Any]:
        """
        Preserve structured insight/risk entries.

        The actual factual-claim gate is represented by claim_validation and
        verified_source_backed_claims. This helper only removes malformed
        entries and never invents validation for free-form text.
        """
        if not isinstance(items, list):
            return []

        return [
            item
            for item in items
            if isinstance(item, (str, dict))
        ]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def _score(
        self,
        domain: DomainModule,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute the domain-specific deterministic score.

        Domain scoring strategies must derive quantitative scoring inputs from
        canonical context/snapshots rather than unverified LLM narrative.
        """
        try:
            strategy = domain.get_scoring_strategy()

        except Exception:
            logger.exception(
                "Scoring strategy unavailable for %s",
                domain.name,
            )

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

        # Interface remains compatible with existing domain strategies.
        # The integrity rule is that canonical context, not LLM prose, is the
        # deterministic source of truth.
        return await strategy.score(
            entity_ref,
            context,
            llm_output,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    async def _maybe_await(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Support both synchronous and asynchronous domain hooks."""
        result = func(*args, **kwargs)

        if inspect.isawaitable(result):
            return await result

        return result