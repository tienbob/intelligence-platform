"""
HR domain API router — PLACEHOLDER.

Endpoints to implement:
    GET  /hr/candidates          — List/search candidates
    GET  /hr/candidates/{id}     — Get candidate profile + scores
    POST /hr/candidates/analyze  — Run candidate analysis
    GET  /hr/jobs                — List jobs
    GET  /hr/jobs/{id}           — Get job details
    POST /hr/jobs/match          — Match candidates to a job
    GET  /hr/salary/benchmarks   — Get salary benchmarks
    GET  /hr/skills/taxonomy     — Get skills taxonomy
"""

from __future__ import annotations

from fastapi import APIRouter

hr_router = APIRouter(prefix="/hr", tags=["hr"])


@hr_router.get("/health")
async def hr_domain_health():
    """Health check for the HR domain."""
    return {
        "domain": "hr",
        "version": "0.1.0",
        "status": "placeholder",
        "message": (
            "HR domain is discovered but not yet implemented. "
            "Implement providers, context builder, scoring, and endpoints to activate."
        ),
    }


@hr_router.get("/candidates")
async def list_candidates():
    """List candidates — PLACEHOLDER."""
    return {
        "candidates": [],
        "status": "not_implemented",
        "message": "Implement candidate data ingestion and search.",
    }


@hr_router.get("/jobs")
async def list_jobs():
    """List jobs — PLACEHOLDER."""
    return {
        "jobs": [],
        "status": "not_implemented",
        "message": "Implement job data ingestion and search.",
    }


@hr_router.post("/analyze")
async def create_analysis():
    """Create a candidate/job analysis — PLACEHOLDER."""
    return {
        "status": "not_implemented",
        "message": "Implement HR intelligence analysis pipeline.",
    }