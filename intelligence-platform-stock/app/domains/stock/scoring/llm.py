"""
LLM research analyst service (Sections 30–32).

The LLM provider must be abstracted so the system can switch providers.

This service is **OpenAI-API-compatible**: it uses the OpenAI SDK pointed at a
configurable ``LLM_BASE_URL``. Any provider that exposes an OpenAI-compatible
``/v1/chat/completions`` endpoint works out of the box:

- OpenAI            -> https://api.openai.com/v1
- Gemini            -> https://generativelanguage.googleapis.com/v1beta/openai/
- Azure OpenAI      -> https://<resource>.openai.azure.com/openai/v1
- Local (Ollama)    -> http://localhost:11434/v1
- Local (vLLM)      -> http://localhost:8000/v1

Set ``LLM_PROVIDER`` to a human-readable label (e.g. "openai", "gemini",
"local") for metadata/audit purposes; it does not change the transport.

LLM should:
    Explain market movements, Interpret financial metrics,
    Summarize relevant news, Compare competing explanations,
    Identify catalysts, Identify risks, Construct investment thesis,
    Identify uncertainty, Explain what could invalidate the thesis

LLM should NOT:
    Calculate financial ratios, Invent missing financial data,
    Predict guaranteed prices, Override source data,
    Automatically execute trades
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.intelligence.llm import LLMClient
from app.intelligence.llm.structured_output import extract_json as _extract_json_generic
from app.domains.stock.scoring.analysis_validator import AnalysisValidator, AnalysisValidationError
from app.domains.stock.scoring.evidence import EvidenceAttributor

logger = get_logger(__name__)
settings = get_stock_config()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Prompt version registry (Section 55)
PROMPT_VERSIONS = {
    "company_analysis": "1.1",
    "market_analysis": "1.0",
    "risk_analysis": "1.0",
    "portfolio_analysis": "1.0",
}


class LLMService:
    """
    Abstracted LLM service for research analysis.

    Uses the OpenAI SDK against a configurable ``LLM_BASE_URL`` so any
    OpenAI-compatible provider (OpenAI, Gemini, Azure, local) works.
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
        self._client: Any = None
        self._engine: LLMClient | None = None

    def _get_engine(self) -> LLMClient:
        """Get the framework LLM engine configured from Stock settings."""
        if self._engine is None:
            self._engine = LLMClient(
                api_key=self.api_key,
                model=self.model,
                base_url=settings.LLM_BASE_URL,
                provider=self.provider,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                max_attempts=settings.LLM_MAX_ATTEMPTS,
                retry_base_delay=settings.LLM_RETRY_BASE_DELAY,
                retry_max_delay=settings.LLM_RETRY_MAX_DELAY,
                fallback_model=settings.LLM_FALLBACK_MODEL,
            )
        return self._engine

    async def _get_client(self) -> Any:
        """Get the OpenAI-compatible client (lazy init via framework engine)."""
        return await self._get_engine().get_client()

    @staticmethod
    def load_prompt(name: str) -> str:
        """Load a prompt template from the prompts directory."""
        prompt_path = PROMPTS_DIR / f"{name}.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
        return prompt_path.read_text()

    @staticmethod
    def get_prompt_version(prompt_name: str) -> str:
        """Get version for a prompt template."""
        return PROMPT_VERSIONS.get(prompt_name, "1.0")

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

        Phase 5: Added evidence attribution, structured output validation,
        and prompt version tracking.

        Returns the LLM output as a parsed JSON dict (Section 31 schema).
        """
        client = await self._get_client()

        # §32: Inject available evidence source IDs into the LLM context so the
        # model can cite them via `evidence_ids` in its structured output.
        if evidence_attributor is not None:
            snapshot_sources = []
            for item in (context.get("news_snapshot") or {}).get("recent_news", []):
                if item.get("id") is not None:
                    snapshot_sources.append({
                        "id": item["id"],
                        "content": f"{item.get('title', '')} {item.get('summary') or ''}",
                        "metadata": {"source": item.get("source"), "published_at": item.get("published_at")},
                    })
            evidence_attributor.register_sources({"snapshot_news": snapshot_sources})
            context["evidence_passages"] = list(evidence_attributor.source_registry.values())
            context["available_evidence_ids"] = sorted(evidence_attributor.source_registry.keys())

        # Build the user message from context
        context_json = json.dumps(context, indent=2, default=str)
        user_message = user_query or f"Analyze the following data and provide a structured investment analysis.\n\nContext:\n{context_json}"

        # OpenAI-compatible chat completions call via the framework engine.
        # Works for OpenAI, Gemini, Azure, and local providers via LLM_BASE_URL.
        engine = self._get_engine()
        result, tokens_used = await engine.chat_json(system_prompt, user_message)

        # Phase 5: Validate structured output (Section 54)
        prompt_version = self.get_prompt_version(prompt_name) if prompt_name else "1.0"

        try:
            if analysis_type == "company":
                AnalysisValidator.validate_company_analysis(result)
            elif analysis_type == "risk":
                AnalysisValidator.validate_risk_analysis(result)
            elif analysis_type == "portfolio":
                AnalysisValidator.validate_portfolio_analysis(result)
        except AnalysisValidationError as exc:
            logger.error("LLM output validation failed: %s", exc)
            raise

        # Phase 4b: Citation-support check — the validator proves cited IDs
        # exist; this proves the cited content can plausibly back the claim.
        # LLMs occasionally cite a valid-but-unrelated document from the
        # evidence set (e.g. a fundamentals claim citing an unrelated news
        # article); drop those citations rather than assert false links.
        if evidence_attributor is not None:
            for item in result.get("causes", []):
                supported = evidence_attributor.filter_supported_evidence_ids(item)
                dropped = [eid for eid in item.get("evidence_ids", []) if eid not in supported]
                if dropped:
                    logger.warning(
                        "Dropped unsupported evidence citation(s) %s for claim: %s",
                        dropped,
                        (item.get("cause") or item.get("claim") or "")[:80],
                    )
                item["evidence_ids"] = supported
                item["evidence_status"] = "plausible_support" if supported else "unverified"
            unverified = [item for item in result.get("causes", []) if not item.get("evidence_ids")]
            if unverified:
                result["citation_warnings"] = [
                    {"claim": item.get("cause"), "reason": "No cited passage passed the citation support check"}
                    for item in unverified
                ]
                result["causes"] = [item for item in result.get("causes", []) if item.get("evidence_ids")]

        # Phase 5: Evidence attribution (Section 32) — attach the evidence
        # package backing whichever `evidence_ids` the LLM cited. The valid
        # ID list was already injected into `context` above, before the call.
        if evidence_attributor is not None:
            evidence_package = evidence_attributor.build_evidence_package(
                context.get("rag_context", {})
            )
            result["evidence"] = evidence_package

        # Phase 5: Persist full analysis metadata (Section 55-56)
        result["_meta"] = engine.build_meta(
            tokens_used=tokens_used,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            analysis_type=analysis_type,
        )

        return result

    @staticmethod
    def _extract_json(content: str | None) -> dict[str, Any]:
        """Extract JSON from an imperfect LLM response (framework core)."""
        return _extract_json_generic(content)

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
            system_prompt, context,
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
            system_prompt, context,
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
            system_prompt, context,
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
            system_prompt, context,
            evidence_attributor=evidence_attributor,
            analysis_type="portfolio",
            prompt_name="portfolio_analysis",
        )