"""
LLM research analyst service (Sections 30–32).

The LLM provider must be abstracted so the system can switch providers.

This service is OpenAI-API-compatible: it uses the framework LLM client
against a configurable ``LLM_BASE_URL``. Any provider that exposes an
OpenAI-compatible chat-completions endpoint works out of the box.

Examples:

- OpenAI
- Gemini
- Azure OpenAI
- Local Ollama
- Local vLLM

Set ``LLM_PROVIDER`` to a human-readable label for metadata/audit purposes.
It does not change the transport.

LLM responsibilities:

    Explain market movements
    Interpret financial metrics
    Summarize relevant news
    Compare competing explanations
    Identify catalysts
    Identify risks
    Construct investment thesis
    Identify uncertainty
    Explain what could invalidate the thesis

LLM must NOT:

    Calculate financial ratios
    Invent missing financial data
    Predict guaranteed prices
    Override source data
    Automatically execute trades

Evidence invariants:

1. The LLM may cite only evidence made available to it.
2. Evidence IDs are treated as opaque identifiers, not as proof of truth.
3. Every cited evidence ID must resolve to an actual evidence record.
4. Evidence identity must be preserved exactly.
5. The LLMService does not promote an evidence ID to SUPPORTED merely
   because the ID exists.
6. Claim-level truth is delegated to the EvidenceResolver / ClaimValidator.
7. Available evidence and cited evidence are kept separate.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable

from app.core.logging import get_logger
from app.domains.stock.config import get_stock_config
from app.domains.stock.scoring.analysis_validator import (
    AnalysisValidationError,
    AnalysisValidator,
)
from app.domains.stock.scoring.evidence import EvidenceAttributor
from app.intelligence.llm import LLMClient
from app.intelligence.llm.structured_output import (
    extract_json as _extract_json_generic,
)

logger = get_logger(__name__)
settings = get_stock_config()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# Prompt version registry (Section 55)
PROMPT_VERSIONS = {
    "company_analysis": "1.0",
    "market_analysis": "1.0",
    "risk_analysis": "1.0",
    "portfolio_analysis": "1.0",
}


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    """Return value as a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _normalize_evidence_id(value: Any) -> str | None:
    """
    Normalize an evidence identifier.

    Evidence IDs are intentionally treated as opaque strings. We do not
    attempt to infer entity_type/entity_id from the identifier because doing
    so would recreate the provenance bug this layer is intended to prevent.
    """
    if value is None:
        return None

    normalized = str(value).strip()

    return normalized or None


def _iter_evidence_ids(value: Any) -> Iterable[str]:
    """
    Extract normalized evidence IDs from a value.

    Supports the common structured-output shapes:

        ["news_123", "sec_filing_456"]

    and defensive handling of scalar values.
    """
    if value is None:
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            normalized = _normalize_evidence_id(item)
            if normalized:
                yield normalized
        return

    normalized = _normalize_evidence_id(value)

    if normalized:
        yield normalized


def _extract_cited_evidence_ids(result: dict[str, Any]) -> list[str]:
    """
    Extract evidence IDs from the structured LLM result.

    The primary contract is ``evidence_ids`` on claim/source objects.

    We deliberately inspect recursively so nested structured claims cannot
    bypass citation validation.
    """
    found: list[str] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).strip().lower()

                if normalized_key in {
                    "evidence_ids",
                    "evidence_id",
                }:
                    for evidence_id in _iter_evidence_ids(child):
                        if evidence_id not in seen:
                            seen.add(evidence_id)
                            found.append(evidence_id)

                # Continue walking because evidence IDs may be nested inside
                # claims, source blocks, explanations, or other structures.
                walk(child)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)

    return found


def _evidence_registry(attributor: EvidenceAttributor) -> dict[str, Any]:
    """
    Safely retrieve the evidence registry from an attributor.

    The existing implementation exposes ``source_registry``. This helper
    keeps this service tolerant of a future mapping/property implementation.
    """
    registry = getattr(attributor, "source_registry", None)

    if isinstance(registry, dict):
        return registry

    return {}


def _identity_from_source(
    evidence_id: str,
    source: Any,
) -> dict[str, Any]:
    """
    Convert a registry source object into an audit-safe identity payload.

    This function does NOT invent missing identity.

    Missing fields remain absent rather than being synthesized from the
    evidence ID.
    """
    if isinstance(source, dict):
        identity = dict(source)
    else:
        identity = {}

        for field in (
            "entity_type",
            "entity_id",
            "company_id",
            "source_id",
            "provider",
            "source",
            "source_name",
            "source_type",
            "status",
            "resolution_status",
            "period",
            "filing_type",
            "accession_number",
        ):
            value = getattr(source, field, None)

            if value is not None:
                identity[field] = value

    identity["evidence_id"] = evidence_id

    return identity


def _build_evidence_catalog(
    attributor: EvidenceAttributor,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Build the evidence catalog exposed to the LLM.

    Returns:

        available_ids
        available_evidence

    The catalog contains identity metadata where available, but it never
    fabricates entity_type/entity_id/provider/company information.
    """
    registry = _evidence_registry(attributor)

    available_ids: list[str] = []
    available_evidence: list[dict[str, Any]] = []

    for raw_id, source in registry.items():
        evidence_id = _normalize_evidence_id(raw_id)

        if not evidence_id:
            continue

        if evidence_id in available_ids:
            continue

        available_ids.append(evidence_id)
        available_evidence.append(
            _identity_from_source(
                evidence_id,
                source,
            )
        )

    return available_ids, available_evidence


def _validate_cited_ids_exist(
    result: dict[str, Any],
    attributor: EvidenceAttributor,
) -> dict[str, Any]:
    """
    Validate that every evidence ID cited by the LLM exists in the evidence
    registry.

    This is an ID-integrity check only.

    It does NOT mean:

        evidence exists -> claim is supported.

    Claim support remains the responsibility of the evidence resolver and
    claim validator.
    """
    registry = _evidence_registry(attributor)
    cited_ids = _extract_cited_evidence_ids(result)

    if not cited_ids:
        return result

    valid_ids = {
        normalized
        for raw_id in registry.keys()
        if (normalized := _normalize_evidence_id(raw_id))
    }

    invalid_ids = [
        evidence_id
        for evidence_id in cited_ids
        if evidence_id not in valid_ids
    ]

    if invalid_ids:
        logger.warning(
            "LLM cited evidence IDs that are not available: %s",
            invalid_ids,
        )

        # Preserve the model output but explicitly annotate the invalid
        # citation IDs. Downstream claim validation can then mark those
        # citations INVALID rather than accidentally treating them as
        # supported.
        result.setdefault("_evidence_validation", {})
        result["_evidence_validation"].update(
            {
                "status": "invalid_citations",
                "invalid_evidence_ids": invalid_ids,
                "cited_evidence_ids": cited_ids,
            }
        )

    else:
        result.setdefault("_evidence_validation", {})
        result["_evidence_validation"].update(
            {
                "status": "ids_resolved",
                "cited_evidence_ids": cited_ids,
                "invalid_evidence_ids": [],
            }
        )

    return result


def _attach_cited_evidence_identities(
    result: dict[str, Any],
    attributor: EvidenceAttributor,
) -> dict[str, Any]:
    """
    Attach the actual registry identities for cited evidence.

    This is useful for downstream resolver/validator stages and audit logs.

    Crucially, this does not change the evidence IDs or reinterpret them.
    """
    registry = _evidence_registry(attributor)
    cited_ids = _extract_cited_evidence_ids(result)

    cited_evidence: list[dict[str, Any]] = []

    for evidence_id in cited_ids:
        source = registry.get(evidence_id)

        if source is None:
            continue

        cited_evidence.append(
            _identity_from_source(
                evidence_id,
                source,
            )
        )

    result.setdefault("_evidence_validation", {})
    result["_evidence_validation"]["cited_evidence"] = cited_evidence

    return result


# ---------------------------------------------------------------------------
# LLM service
# ---------------------------------------------------------------------------


class LLMService:
    """
    Abstracted LLM service for research analysis.

    Uses the framework LLM engine against a configurable ``LLM_BASE_URL`` so
    any OpenAI-compatible provider works.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        self.provider = provider or settings.LLM_PROVIDER

        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

        self._engine: LLMClient | None = None

    # ------------------------------------------------------------------
    # Framework client
    # ------------------------------------------------------------------

    def _get_engine(self) -> LLMClient:
        """Get the framework LLM engine configured from stock settings."""
        if self._engine is None:
            self._engine = LLMClient(
                api_key=self.api_key,
                model=self.model,
                base_url=settings.LLM_BASE_URL,
                provider=self.provider,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        return self._engine

    async def _get_client(self) -> Any:
        """Get the OpenAI-compatible client lazily via the framework engine."""
        return await self._get_engine().get_client()

    # ------------------------------------------------------------------
    # Prompt management
    # ------------------------------------------------------------------

    @staticmethod
    def load_prompt(name: str) -> str:
        """Load a prompt template from the prompts directory."""
        prompt_path = PROMPTS_DIR / f"{name}.txt"

        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt template not found: {prompt_path}"
            )

        return prompt_path.read_text(encoding="utf-8")

    @staticmethod
    def get_prompt_version(prompt_name: str) -> str:
        """Get the registered version for a prompt template."""
        return PROMPT_VERSIONS.get(prompt_name, "1.0")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze(
        self,
        system_prompt: str,
        context: dict[str, Any],
        user_query: str | None = None,
        evidence_attributor: EvidenceAttributor | None = None,
        analysis_type: str = "company",
        prompt_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Run LLM analysis with structured context.

        Processing pipeline:

            1. Build isolated context
            2. Inject evidence catalog
            3. Generate structured LLM output
            4. Validate output schema
            5. Validate cited evidence IDs
            6. Attach resolved evidence identities
            7. Build evidence package
            8. Attach framework metadata

        Important:

        Evidence ID existence is NOT treated as claim support. The actual
        evidence resolver/claim validator must perform source, company,
        period, metric, and value validation.
        """
        if not isinstance(context, dict):
            raise TypeError("LLM analysis context must be a dictionary")

        engine = self._get_engine()

        # --------------------------------------------------------------
        # 1. Isolate caller context
        # --------------------------------------------------------------

        # The previous implementation mutated the caller via setdefault().
        # Context can be shared by multiple analysis stages, so mutation here
        # is unsafe.
        analysis_context = copy.deepcopy(context)

        # --------------------------------------------------------------
        # 2. Inject evidence catalog
        # --------------------------------------------------------------

        if evidence_attributor is not None:
            available_ids, available_evidence = _build_evidence_catalog(
                evidence_attributor
            )

            # Keep the old field for backwards compatibility.
            analysis_context["available_evidence_ids"] = available_ids

            # New explicit catalog gives the model enough information to
            # choose the correct evidence class without guessing.
            analysis_context["available_evidence"] = available_evidence

            # Explicit instruction that these IDs are citations, not proof.
            analysis_context["evidence_citation_rules"] = {
                "must_use_only_available_ids": True,
                "must_not_invent_ids": True,
                "evidence_id_is_not_proof_of_claim": True,
                "claim_support_is_validated_downstream": True,
            }

        # --------------------------------------------------------------
        # 3. Build user message
        # --------------------------------------------------------------

        context_json = json.dumps(
            analysis_context,
            indent=2,
            default=str,
            ensure_ascii=False,
        )

        if user_query:
            user_message = user_query
        else:
            user_message = (
                "Analyze the following data and provide a structured "
                "investment analysis.\n\n"
                "Context:\n"
                f"{context_json}"
            )

        # --------------------------------------------------------------
        # 4. LLM generation
        # --------------------------------------------------------------

        result, tokens_used = await engine.chat_json(
            system_prompt,
            user_message,
        )

        if not isinstance(result, dict):
            raise AnalysisValidationError(
                "LLM returned a non-object structured result"
            )

        # --------------------------------------------------------------
        # 5. Schema validation
        # --------------------------------------------------------------

        self._validate_analysis_schema(
            result=result,
            analysis_type=analysis_type,
        )

        # --------------------------------------------------------------
        # 6. Evidence ID validation
        # --------------------------------------------------------------

        if evidence_attributor is not None:
            result = _validate_cited_ids_exist(
                result,
                evidence_attributor,
            )

            result = _attach_cited_evidence_identities(
                result,
                evidence_attributor,
            )

        # --------------------------------------------------------------
        # 7. Evidence package
        # --------------------------------------------------------------

        if evidence_attributor is not None:
            rag_context = analysis_context.get("rag_context", {})

            if not isinstance(rag_context, dict):
                rag_context = {}

            try:
                evidence_package = (
                    evidence_attributor.build_evidence_package(
                        rag_context
                    )
                )

                # Evidence package is supplementary context. It must not
                # overwrite the LLM's citation identities.
                result["evidence"] = evidence_package

            except Exception:
                logger.exception(
                    "Failed to build evidence package for analysis_type=%s",
                    analysis_type,
                )

                result.setdefault("_evidence_validation", {})
                result["_evidence_validation"][
                    "package_status"
                ] = "unavailable"

        # --------------------------------------------------------------
        # 8. Metadata
        # --------------------------------------------------------------

        prompt_version = (
            self.get_prompt_version(prompt_name)
            if prompt_name
            else "1.0"
        )

        result["_meta"] = engine.build_meta(
            tokens_used=tokens_used,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            analysis_type=analysis_type,
        )

        return result

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_analysis_schema(
        result: dict[str, Any],
        analysis_type: str,
    ) -> None:
        """
        Validate the structured analysis schema.

        Evidence truth is intentionally NOT checked here.
        """
        try:
            if analysis_type == "company":
                AnalysisValidator.validate_company_analysis(result)

            elif analysis_type == "risk":
                AnalysisValidator.validate_risk_analysis(result)

            elif analysis_type == "portfolio":
                AnalysisValidator.validate_portfolio_analysis(result)

            # Market analysis currently has no dedicated validator in the
            # existing implementation. Keep generation compatible with the
            # current architecture rather than inventing a new contract.

        except AnalysisValidationError as exc:
            logger.error(
                "LLM output validation failed for analysis_type=%s: %s",
                analysis_type,
                exc,
            )
            raise

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(content: str | None) -> dict[str, Any]:
        """Extract JSON from an imperfect LLM response."""
        return _extract_json_generic(content)

    # ------------------------------------------------------------------
    # Specialized analyses
    # ------------------------------------------------------------------

    async def analyze_company(
        self,
        context: dict[str, Any],
        evidence_attributor: EvidenceAttributor | None = None,
    ) -> dict[str, Any]:
        """
        Run company analysis using the company analysis prompt.

        Section 30: LLM responsibilities.
        """
        system_prompt = self.load_prompt("company_analysis")

        return await self.analyze(
            system_prompt,
            context,
            evidence_attributor=evidence_attributor,
            analysis_type="company",
            prompt_name="company_analysis",
        )

    async def analyze_market(
        self,
        context: dict[str, Any],
        evidence_attributor: EvidenceAttributor | None = None,
    ) -> dict[str, Any]:
        """Run market analysis using the market analysis prompt."""
        system_prompt = self.load_prompt("market_analysis")

        return await self.analyze(
            system_prompt,
            context,
            evidence_attributor=evidence_attributor,
            analysis_type="market",
            prompt_name="market_analysis",
        )

    async def analyze_risk(
        self,
        context: dict[str, Any],
        evidence_attributor: EvidenceAttributor | None = None,
    ) -> dict[str, Any]:
        """Run risk analysis using the risk analysis prompt."""
        system_prompt = self.load_prompt("risk_analysis")

        return await self.analyze(
            system_prompt,
            context,
            evidence_attributor=evidence_attributor,
            analysis_type="risk",
            prompt_name="risk_analysis",
        )

    async def analyze_portfolio(
        self,
        context: dict[str, Any],
        evidence_attributor: EvidenceAttributor | None = None,
    ) -> dict[str, Any]:
        """Run portfolio analysis using the portfolio analysis prompt."""
        system_prompt = self.load_prompt("portfolio_analysis")

        return await self.analyze(
            system_prompt,
            context,
            evidence_attributor=evidence_attributor,
            analysis_type="portfolio",
            prompt_name="portfolio_analysis",
        )