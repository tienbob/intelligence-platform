"""
Core contracts (Protocols) that every domain must fulfill.

These define the interfaces the intelligence engine depends on.
Domains implement these contracts; the core never imports domain code directly.

Design principles
-----------------
1. The framework owns *how* (retrieval, embedding, LLM calls, validation,
   orchestration). The domain owns *what* (entities, sources, scoring logic,
   prompts).
2. Providers are **capability-based**, not monolithic. A domain declares a
   set of named providers, each implementing whichever capability protocols
   apply to it. The framework never assumes every provider has one generic
   ``fetch()`` — see ``EntityDataProvider`` and friends below. Domains are
   free to define additional capability protocols for their own needs.
3. Everything in this file is intentionally minimal. If a method on
   ``DomainModule`` cannot name a framework-level consumer, it does not
   belong here.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.intelligence.prompts import PromptRegistry
from app.shared.entities import (
    AnalysisRequest,
    AnalysisResult,
    EntityRef,
    Evidence,
    IntelligenceContext,
    Observation,
)

# Re-exported so domains can depend on ``app.intelligence.contracts``
# as their single framework-import surface.
__all__ = [
    "AnalysisRequest",
    "AnalysisResult",
    "CapabilityProvider",
    "ContextBuilder",
    "DomainModule",
    "EntityDataProvider",
    "EntityRef",
    "Evidence",
    "IntelligenceContext",
    "IntelligenceTask",
    "NewsProvider",
    "Normalizer",
    "Observation",
    "PromptRegistry",
    "Provider",
    "ScoringStrategy",
    "SearchProvider",
    "TimeSeriesProvider",
]


# ── Capability-based provider protocols ─────────────────────────
#
# These are the framework's *capability vocabulary*. A provider is not
# "a thing with fetch()"; it is "a thing that can do X". Domains mix and
# match capabilities, and may declare their own domain-specific ones
# alongside these.


@runtime_checkable
class CapabilityProvider(Protocol):
    """Marker protocol implemented by all data providers."""

    provider_name: str

    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
        ...


@runtime_checkable
class EntityDataProvider(CapabilityProvider, Protocol):
    """
    Fetches structured records about an entity on demand.

    This is the closest generalization of the legacy ``fetch`` contract.
    Implement it only for request-time fetching; worker-owned ingestion
    (the recommended pattern) does not require it.
    """

    async def fetch(
        self, entity_ref: EntityRef, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Fetch raw records about an entity from an external source."""
        ...


@runtime_checkable
class TimeSeriesProvider(CapabilityProvider, Protocol):
    """Fetches time-series observations for an entity (prices, metrics, …)."""

    async def get_series(
        self, entity_ref: EntityRef, metric: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Fetch a named time series for an entity."""
        ...


@runtime_checkable
class NewsProvider(CapabilityProvider, Protocol):
    """Searches external news/document sources."""

    async def search_news(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Search news/documents matching a query."""
        ...


@runtime_checkable
class SearchProvider(CapabilityProvider, Protocol):
    """Performs open-ended retrieval against an external corpus."""

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Retrieve documents/records matching a query."""
        ...


@runtime_checkable
class Provider(EntityDataProvider, Protocol):
    """
    DEPRECATED alias retained for backward compatibility.

    Historically this was the universal provider contract. It is now just
    the ``EntityDataProvider`` capability; prefer declaring which capabilities
    a provider actually implements. Will be removed once no code references it.
    """



@runtime_checkable
class Normalizer(Protocol):
    """Transforms raw provider data into canonical domain observations."""

    async def normalize(
        self, raw_data: list[dict[str, Any]], entity_ref: EntityRef
    ) -> list[Observation]:
        """Normalize raw data into domain observations."""
        ...


@runtime_checkable
class ContextBuilder(Protocol):
    """Builds structured IntelligenceContext for LLM consumption."""

    async def build(
        self,
        entity_ref: EntityRef,
        evidence: list[Evidence],
        observations: list[Observation],
        rag_context: dict[str, Any],
        **kwargs: Any,
    ) -> IntelligenceContext:
        """Build the full context for LLM analysis."""
        ...


@runtime_checkable
class ScoringStrategy(Protocol):
    """Computes a score for an entity based on domain-specific logic."""

    async def score(
        self,
        entity_ref: EntityRef,
        context: IntelligenceContext,
        llm_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute a domain-specific score.

        Returns a dict with at minimum:
            - score: float (0-100)
            - confidence: float (0-1)
            - recommendation: str
            - components: dict[str, float]
        """
        ...


@runtime_checkable
class IntelligenceTask(Protocol):
    """A background intelligence task (ingestion, analysis, scoring, etc.)."""

    name: str
    interval_minutes: int
    run_immediately: bool

    async def execute(self) -> None:
        """Execute the task."""
        ...


@runtime_checkable
class DomainModule(Protocol):
    """
    The top-level contract every domain pack must implement.

    This is what the registry discovers and what main.py wires up.

    Every method here has a concrete framework-level consumer:
      - get_api_router        → main.py mounts at /api/v1
      - get_internal_router   → main.py mounts at /internal (optional)
      - get_intelligence_tasks→ app/workers/scheduler.py
      - get_providers         → IntelligencePipeline ingestion stage
      - get_normalizers       → IntelligencePipeline normalization stage
      - get_context_builder   → IntelligencePipeline context stage
      - get_scoring_strategy  → IntelligencePipeline scoring stage (optional)
      - get_prompts           → IntelligencePipeline LLM stage
    """

    name: str
    version: str

    def get_providers(self) -> dict[str, Any]:
        """
        Return the domain's data providers, keyed by role
        (e.g. {"market": …, "financials": …, "news": …}).

        Providers implement whichever capability protocols apply to them
        (see ``CapabilityProvider`` and friends above). Worker-owned
        ingestion domains may return providers without on-demand fetch
        capabilities — the pipeline detects this and skips generic ingestion.
        """
        ...

    def get_normalizers(self) -> dict[str, Normalizer]:
        """Return the domain's data normalizers."""
        ...

    def get_context_builder(self) -> ContextBuilder:
        """Return the domain's context builder."""
        ...

    def get_scoring_strategy(self) -> ScoringStrategy | None:
        """Return the domain's scoring strategy, or None if scoring is not needed."""
        ...

    def get_intelligence_tasks(self) -> list[IntelligenceTask]:
        """Return the domain's background tasks."""
        ...

    def get_api_router(self):
        """Return the domain's FastAPI APIRouter."""
        ...

    def get_internal_router(self):
        """
        Optionally return a service-to-service router (mounted at /internal).

        Domains that expose endpoints for trusted internal callers (e.g. an
        external BFF gateway) implement this; the app mounts whatever is
        returned with internal-service authentication. Optional — core checks
        ``hasattr`` so domains without internal endpoints may omit it.
        """
        ...

    def get_prompts(self) -> PromptRegistry:
        """Return the domain's prompt registry."""
        ...

    def get_evidence_attributor(self, context):
        """
        Optionally return a claim→source evidence-attribution service (§32).

        If a domain implements this, the pipeline builds the LLM context
        dict and then passes ``attributor(context)`` to the domain's LLM
        service as ``evidence_attributor``, preserving source attribution
        through the generic framework path. Domains without attribution
        simply omit the method — the pipeline checks ``getattr``/``hasattr``
        like it does for the optional internal router.
        """
        ...