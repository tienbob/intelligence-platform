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
    # App-level retry for transient LLM provider errors (429/5xx/timeouts).
    LLM_MAX_ATTEMPTS: int = 4
    LLM_RETRY_BASE_DELAY: float = 5.0
    LLM_RETRY_MAX_DELAY: float = 60.0

    # ── Embeddings ───────────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

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

    # ── Analysis engine selection (PLAN.md Gate 5.1) ─────────────
    # "legacy"    → shared CompanyAnalysisService orchestration (current
    #               production engine; ContextBuilder + LLMService +
    #               InvestmentScoringEngine under one roof).
    # "framework" → generic IntelligencePipeline via
    #               pipeline_factory.build_stock_pipeline().
    # Both production entry points (API + scheduled worker) route through
    # execute_company_analysis(), which is the ONLY place this is read.
    ANALYSIS_ENGINE: str = "legacy"


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