"""
HR domain Pydantic schemas — PLACEHOLDER.

Schemas to implement:
    - CandidateProfile, CandidateSearchRequest, CandidateAnalysisRequest
    - JobPosting, JobSearchRequest, JobMatchRequest
    - SalaryBenchmarkRequest, SalaryBenchmarkResponse
    - SkillTaxonomyEntry, SkillSearchRequest
    - AnalysisResponse (candidate-job fit result)
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class CandidateAnalysisRequest(BaseModel):
    """Request to analyze a candidate."""
    candidate_id: str
    job_id: Optional[str] = None
    include_salary_benchmark: bool = True
    include_market_demand: bool = True


class AnalysisResponse(BaseModel):
    """Response from a candidate analysis."""
    analysis_id: str
    status: str
    candidate_id: Optional[str] = None
    job_id: Optional[str] = None
    fit_score: Optional[float] = None
    confidence: Optional[float] = None
    recommendation: Optional[str] = None
    analysis: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None