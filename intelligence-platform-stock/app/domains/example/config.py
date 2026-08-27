"""Example domain configuration — minimal settings for validation."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ExampleConfig(BaseSettings):
    """Example-domain-specific configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    SCORE_WEIGHT_QUALITY: float = 0.40
    SCORE_WEIGHT_PRICE: float = 0.30
    SCORE_WEIGHT_DEMAND: float = 0.30
    BASE_CONFIDENCE: float = 0.50


@lru_cache
def get_example_config() -> ExampleConfig:
    return ExampleConfig()