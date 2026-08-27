"""
HR domain configuration.

All HR-specific settings live here. Core settings (database, redis, LLM)
remain in app/core/config.py.

Implement these settings based on your HR data sources and scoring requirements.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HRConfig(BaseSettings):
    """HR-domain-specific configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Provider API Keys ────────────────────────────────────────
    LINKEDIN_API_KEY: Optional[str] = None
    LINKEDIN_BASE_URL: str = "https://api.linkedin.com/v2"

    INDEED_API_KEY: Optional[str] = None
    INDEED_BASE_URL: str = "https://api.indeed.com"

    GLASSDOOR_API_KEY: Optional[str] = None
    GLASSDOOR_BASE_URL: str = "https://api.glassdoor.com"

    GREENHOUSE_API_KEY: Optional[str] = None
    GREENHOUSE_BASE_URL: str = "https://harvest.greenhouse.io/v1"

    LEVELS_FYI_API_KEY: Optional[str] = None

    # ── Background Processing Intervals ──────────────────────────
    CANDIDATE_DATA_UPDATE_INTERVAL_HR: int = 24
    JOB_MARKET_UPDATE_INTERVAL_HR: int = 12
    SALARY_BENCHMARK_UPDATE_INTERVAL_HR: int = 168  # weekly
    SKILLS_TAXONOMY_UPDATE_INTERVAL_HR: int = 720  # monthly
    SCORE_RECALCULATION_INTERVAL_HR: int = 24

    # ── Candidate Scoring Weights ────────────────────────────────
    SCORE_WEIGHT_SKILLS_MATCH: float = 0.35
    SCORE_WEIGHT_EXPERIENCE_FIT: float = 0.25
    SCORE_WEIGHT_SALARY_ALIGNMENT: float = 0.15
    SCORE_WEIGHT_CULTURE_INDICATORS: float = 0.15
    SCORE_WEIGHT_MARKET_DEMAND: float = 0.10

    # ── Recommendation Thresholds ────────────────────────────────
    RECOMMENDATION_THRESHOLDS: list[dict[str, Any]] = Field(default_factory=lambda: [
        {"threshold": 85, "category": "STRONG_HIRE"},
        {"threshold": 70, "category": "HIRE"},
        {"threshold": 55, "category": "CONSIDER"},
        {"threshold": 40, "category": "SCREEN_FURTHER"},
        {"threshold": 0, "category": "PASS"},
    ])

    # ── Data Quality ─────────────────────────────────────────────
    BASE_CONFIDENCE: float = 0.50
    MIN_DATA_QUALITY_FOR_RECOMMENDATION: float = 0.40


@lru_cache
def get_hr_config() -> HRConfig:
    """Return a cached HR config instance."""
    return HRConfig()