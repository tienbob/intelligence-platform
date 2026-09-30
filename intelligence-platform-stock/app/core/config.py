"""
Application configuration.

All settings are loaded from environment variables with sensible defaults.
Never hardcode secrets — always read from the environment.

This module contains ONLY platform-level infrastructure settings.
Domain-specific settings (API keys, scoring weights, intervals) live in
each domain's own config.py (e.g. app/domains/stock/config.py).
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings — platform infrastructure only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    APP_NAME: str = "Intelligence Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    # Deployment environment. "production" (the default) enables the
    # fail-closed startup guard in app/main.py: unset/known-default secrets
    # refuse to boot instead of silently failing open. Local dev must set
    # ENVIRONMENT=development explicitly (docker-compose does).
    ENVIRONMENT: str = "production"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ── Redis cache ──────────────────────────────────────────────
    REDIS_URL: Optional[str] = None
    REDIS_CACHE_ENABLED: bool = False
    REDIS_CACHE_TTL_SECONDS: int = 86400
    REDIS_CACHE_PREFIX: str = "mi:cache:"
    REDIS_CACHE_DB: int = 0
    REDIS_CACHE_TIMEOUT_SEC: float = 2.0

    # ── LLM ──────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: Optional[str] = None
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096

    # ── Embeddings ───────────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # ── Background Processing ────────────────────────────────────
    SCHEDULER_TIMEZONE: str = "UTC"

    # ── Authentication & Authorization ───────────────────────────
    APP_API_KEY: Optional[str] = None
    INTERNAL_SERVICE_KEY: Optional[str] = None
    JWT_SECRET_KEY: str = "change-me-in-production-change-me-in-production-1234"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AUTH_ENABLED: bool = False

    # ── Rate Limiting ────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 60
    RATE_LIMIT_ANALYSIS_PER_MINUTE: int = 10
    RATE_LIMIT_LLM_PER_MINUTE: int = 5
    RATE_LIMIT_PORTFOLIO_PER_MINUTE: int = 20
    # NOTE: these limits are enforced by app.core.rate_limit_middleware,
    # which is mounted in app/main.py. Set RATE_LIMIT_ENABLED=false only in
    # local development if the quota gets in your way (audit S03: the limiter
    # previously existed but was never wired, so limits were effectively off).

    # ── Observability ────────────────────────────────────────────
    METRICS_ENABLED: bool = True
    TRACING_ENABLED: bool = False
    TRACING_EXPORTER_ENDPOINT: Optional[str] = None
    REQUEST_ID_HEADER: str = "X-Request-ID"

    # ── Dead-letter handling ─────────────────────────────────────
    DEAD_LETTER_MAX_ATTEMPTS: int = 5
    DEAD_LETTER_RETRY_BACKOFF_SEC: int = 60

    # ── Backup / Recovery ────────────────────────────────────────
    BACKUP_DIR: str = "./backups"
    BACKUP_RETENTION_DAYS: int = 30
    BACKUP_ENABLED: bool = False
    BACKUP_SCHEDULE_HOUR: int = 2


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()