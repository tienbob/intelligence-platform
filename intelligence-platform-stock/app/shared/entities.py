"""
Domain-neutral entity references and types.

The core intelligence engine operates on these generic concepts.
Domains map their specific entities (Company, Candidate, Property, etc.)
to these neutral references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EntityRef:
    """
    A domain-neutral reference to any entity in any domain.

    Examples:
        stock:    EntityRef(domain="stock", entity_type="company", entity_id="AAPL")
        hr:       EntityRef(domain="hr", entity_type="candidate", entity_id="cand-123")
        legal:    EntityRef(domain="legal", entity_type="case", entity_id="case-456")
    """

    domain: str
    entity_type: str
    entity_id: str

    def __hash__(self) -> int:
        return hash((self.domain, self.entity_type, self.entity_id))


@dataclass
class Evidence:
    """A piece of evidence backing an analysis claim."""

    source_type: str  # e.g. "provider", "document", "database"
    source_name: str  # e.g. "SEC", "LinkedIn", "internal_hr_db"
    metric: str | None = None
    value: Any = None
    period: str | None = None
    confidence: float = 1.0


@dataclass
class Observation:
    """
    A single domain-neutral data point about an entity.

    This is the boundary between a provider (vendor response) and evidence
    (a source-backed claim):

        Vendor response
              ↓
        Observation   ← this type (generic)
              ↓
        Normalizer
              ↓
        Evidence

    ``kind`` names the type of observation (e.g. "news", "quote", "filings",
    "employee") so a second domain can reuse the same pipeline without the
    framework knowing what those kinds mean.
    """

    entity_ref: EntityRef
    observed_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    freshness: str = "daily"  # real_time, near_real_time, delayed, daily, quarterly
    kind: str = ""
    confidence: float = 1.0


@dataclass
class AnalysisRequest:
    """A domain-neutral analysis request."""

    entity_ref: EntityRef
    analysis_type: str = "comprehensive"
    parameters: dict[str, Any] = field(default_factory=dict)
    include_context: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """A domain-neutral analysis result."""

    entity_ref: EntityRef
    status: str  # queued, running, completed, failed
    summary: str = ""
    score: float | None = None
    confidence: float = 0.0
    recommendation: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class IntelligenceContext:
    """
    The structured context passed to the LLM for analysis.

    Built by the domain's ContextBuilder, consumed by the core LLM service.
    """

    entity: dict[str, Any] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    rag_context: dict[str, Any] = field(default_factory=dict)
    domain_snapshots: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)