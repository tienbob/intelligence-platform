"""
Pydantic schemas for analysis API (Sections 31, 35, 46).

Implements the LLM output schema (Section 31) and investment
recommendation schema (Section 35).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────────


class AnalysisRequest(BaseModel):
    """POST /api/v1/analysis/company request (Section 46)."""

    ticker: str
    time_horizon: str = "medium_term"  # short_term | medium_term | long_term
    include_news: bool = True
    include_fundamentals: bool = True
    include_technical: bool = True
    include_macro: bool = True


class AnalysisCreateResponse(BaseModel):
    """202 Accepted response when analysis job is queued."""

    analysis_id: str
    status: str = "queued"


# ── LLM output schema (Section 31) ───────────────────────────────


class Cause(BaseModel):
    cause: str
    impact: str = "medium"  # high | medium | low
    confidence: float = Field(ge=0, le=1)


class SourceReference(BaseModel):
    """Source-backed AI claim (Section 32)."""

    type: str
    source: str
    metric: Optional[str] = None
    value: Optional[float] = None
    period: Optional[str] = None


class LLMAnalysisOutput(BaseModel):
    """Structured LLM output (Section 31)."""

    summary: str
    market_interpretation: str
    causes: list[Cause] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    investment_thesis: str
    invalidating_conditions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    source_backed_claims: list[dict[str, Any]] = Field(default_factory=list)


# ── Investment recommendation (Section 35) ───────────────────────


class InvestmentRecommendation(BaseModel):
    score: float
    confidence: float
    recommendation: str  # BUY | WATCH | HOLD | AVOID
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidating_conditions: list[str] = Field(default_factory=list)
    recommended_weight: Optional[float] = None


# ── Confidence breakdown ─────────────────────────────────────────


class ConfidenceBreakdown(BaseModel):
    """Separate confidence components (Phase B).

    ``overall`` is computed by Python, not by the LLM.
    """

    data: float = Field(ge=0, le=1)
    quantitative: float = Field(ge=0, le=1)
    llm: float = Field(ge=0, le=1)
    overall: float = Field(ge=0, le=1)


# ── Full analysis response ───────────────────────────────────────


class AnalysisResponse(BaseModel):
    """GET /api/v1/analysis/{analysis_id} response (Section 46)."""

    analysis_id: str
    status: str
    ticker: Optional[str] = None
    investment_score: Optional[float] = None
    risk_score: Optional[float] = None
    confidence: Optional[float] = None
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    source_backed_claims: list[dict[str, Any]] = Field(default_factory=list)
    analysis: Optional[dict[str, Any]] = None
    recommendation: Optional[InvestmentRecommendation] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Market overview (Section 47) ─────────────────────────────────


class MarketOverview(BaseModel):
    market: dict[str, Any]
    indices: dict[str, Any] = Field(default_factory=dict)
    top_movers: list[dict[str, Any]] = Field(default_factory=list)
    # Distinguish "no movers exist" from "no data available".
    top_movers_status: str = "ok"  # ok | no_data | unavailable
    top_movers_reason: str | None = None
    major_events: list[dict[str, Any]] = Field(default_factory=list)
    macro_environment: dict[str, Any] = Field(default_factory=dict)


# ── Investment opportunities (Section 48) ────────────────────────


class InvestmentOpportunity(BaseModel):
    ticker: str
    score: float
    risk_score: float
    volatility: Optional[float] = None
    sector: Optional[str] = None
    confidence: float
    recommendation: str = "NEUTRAL"
    reason: str
    recommended_weight: float


class InvestmentOpportunitiesResponse(BaseModel):
    opportunities: list[InvestmentOpportunity]