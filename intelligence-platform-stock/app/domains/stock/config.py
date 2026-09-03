"""
Stock domain configuration.

Extracted from the original core/config.py — all stock-specific settings
live here now. Core settings (database, redis, LLM, security) remain in
app/core/config.py.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StockConfig(BaseSettings):
    """Stock-domain-specific configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Provider API Keys ────────────────────────────────────────
    MASSIVE_API_KEY: Optional[str] = None
    MASSIVE_BASE_URL: str = "https://api.massive.com"
    MASSIVE_RATE_LIMIT: int = 5
    MASSIVE_ENABLE_PAID_ENDPOINTS: bool = False

    SEC_USER_AGENT: str = "Market Intelligence research@example.com"
    SEC_BASE_URL: str = "https://data.sec.gov"
    SEC_SUBMISSIONS_BASE_URL: str = "https://data.sec.gov/submissions"

    FRED_API_KEY: Optional[str] = None
    FRED_BASE_URL: str = "https://api.stlouisfed.org/fred"

    FMP_API_KEY: Optional[str] = None
    FMP_BASE_URL: str = "https://financialmodelingprep.com/stable"

    FINNHUB_API_KEY: Optional[str] = None
    FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"

    # ── LLM ──────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: Optional[str] = None
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096

    # NOTE: embedding settings (EMBEDDING_PROVIDER / EMBEDDING_API_KEY /
    # EMBEDDING_MODEL / EMBEDDING_DIMENSIONS) are NOT duplicated here. They are
    # platform infrastructure owned by app/core/config.py — the stock-domain
    # copy pre-dates the framework embedding core and carried a stale 1536-dim
    # default that could drift from the DB's vector(3072) (MIGRATION_FIX_PLAN
    # §P1, Gate 4.2). Single source of truth: app/core/config.py.

    # ── Background Processing Intervals ──────────────────────────
    MARKET_DATA_UPDATE_INTERVAL_MIN: int = 5
    NEWS_PROCESSING_INTERVAL_MIN: int = 10
    ANOMALY_DETECTION_INTERVAL_MIN: int = 15
    EVENT_ANALYSIS_INTERVAL_HR: int = 1
    FUNDAMENTALS_UPDATE_INTERVAL_HR: int = 24
    SCORE_RECALCULATION_INTERVAL_HR: int = 24

    # ── Data Freshness (seconds) ─────────────────────────────────
    REAL_TIME_MAX_AGE_SEC: int = 60
    NEAR_REAL_TIME_MAX_AGE_SEC: int = 300
    DELAYED_MAX_AGE_SEC: int = 900
    DAILY_MAX_AGE_SEC: int = 86400

    # ── Investment Scoring Weights ───────────────────────────────
    SCORE_WEIGHT_FUNDAMENTAL: float = 0.30
    SCORE_WEIGHT_VALUATION: float = 0.20
    SCORE_WEIGHT_GROWTH: float = 0.15
    SCORE_WEIGHT_TECHNICAL: float = 0.10
    SCORE_WEIGHT_SENTIMENT: float = 0.10
    SCORE_WEIGHT_CATALYST: float = 0.10
    SCORE_WEIGHT_RISK: float = 0.15

    # ── Portfolio Constraints ────────────────────────────────────
    DEFAULT_MIN_CASH_PCT: float = 0.20
    DEFAULT_MAX_POSITION_WEIGHT: float = 0.15
    DEFAULT_MAX_SECTOR_WEIGHT: float = 0.30
    DEFAULT_MAX_PORTFOLIO_VOLATILITY: float = 0.25

    # ── Anomaly Thresholds ───────────────────────────────────────
    ANOMALY_MOVEMENT_THRESHOLD: float = 80.0
    PRICE_CHANGE_SCORE_WEIGHT: float = 0.35
    VOLUME_SCORE_WEIGHT: float = 0.25
    VOLATILITY_SCORE_WEIGHT: float = 0.20
    TECHNICAL_SCORE_WEIGHT: float = 0.20

    # ── Scoring Versioning ───────────────────────────────────────
    SCORING_MODEL: str = "investment_score_v1"
    SCORING_VERSION: str = "1.0"

    # NOTE: the ANALYSIS_ENGINE flag (PLAN Gate 5.1) was removed after
    # Gate 6 — the framework is the only production engine and
    # execute_company_analysis() has a single code path. Rollback = git
    # revert to the pre-cleanup revision.

    # ── Recommendation Thresholds ────────────────────────────────
    RECOMMENDATION_THRESHOLDS: List[dict[str, Any]] = Field(default_factory=lambda: [
        {"threshold": 80, "category": "STRONG_OPPORTUNITY"},
        {"threshold": 70, "category": "OPPORTUNITY"},
        {"threshold": 60, "category": "WATCH"},
        {"threshold": 45, "category": "NEUTRAL"},
        {"threshold": 30, "category": "CAUTION"},
        {"threshold": 15, "category": "HIGH_RISK"},
        {"threshold": 0, "category": "AVOID"},
    ])

    # ── Data Quality Weights ─────────────────────────────────────
    DATA_QUALITY_WEIGHTS: dict[str, float] = Field(default_factory=lambda: {
        "price": 0.30,
        "fundamental": 0.30,
        "technical": 0.15,
        "news": 0.15,
        "events": 0.10,
    })

    BASE_CONFIDENCE: float = 0.50
    MIN_DATA_QUALITY_FOR_RECOMMENDATION: float = 0.40


@lru_cache
def get_stock_config() -> StockConfig:
    """Return a cached stock config instance."""
    return StockConfig()