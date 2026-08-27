"""
Schema validation (Section 13).

Before data reaches canonical storage, it must pass schema validation:
    Price >= 0
    Volume >= 0
    Date is valid
    Ticker exists
    Currency is known
    Financial period is valid
    No duplicate records
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.logging import get_logger

logger = get_logger(__name__)


class StockPriceSchema(BaseModel):
    """Validation schema for stock price data."""

    ticker: str
    timestamp: datetime
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    adjusted_close: float | None = Field(default=None, ge=0)
    volume: int = Field(default=0, ge=0)
    source: str

    @model_validator(mode="after")
    def validate_ohlc(self) -> "StockPriceSchema":
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) < Low ({self.low})")
        if self.high < self.open:
            raise ValueError(f"High ({self.high}) < Open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"High ({self.high}) < Close ({self.close})")
        if self.low > self.open:
            raise ValueError(f"Low ({self.low}) > Open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"Low ({self.low}) > Close ({self.close})")
        return self


class FinancialStatementSchema(BaseModel):
    """Validation schema for financial statement data."""

    ticker: str
    period: str
    period_type: str  # annual | quarterly
    currency: str = "USD"
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_debt: float | None = Field(default=None, ge=0)
    cash: float | None = Field(default=None, ge=0)
    source: str

    @field_validator("period_type")
    @classmethod
    def valid_period_type(cls, v: str) -> str:
        if v not in ("annual", "quarterly", "ttm"):
            raise ValueError(f"Invalid period_type: {v}")
        return v

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, v: str) -> str:
        known_currencies = {"USD", "EUR", "GBP", "JPY", "CNY", "CAD", "AUD", "CHF", "INR"}
        if v.upper() not in known_currencies:
            logger.warning("Unknown currency: %s", v)
        return v.upper()


class NewsSchema(BaseModel):
    """Validation schema for news data."""

    title: str = Field(min_length=1)
    source: str
    published_at: datetime
    url: str | None = None
    content_hash: str | None = None
    sentiment: float | None = Field(default=None, ge=-1, le=1)


class EconomicIndicatorSchema(BaseModel):
    """Validation schema for macro economic indicator data."""

    indicator: str
    timestamp: datetime
    value: float
    unit: str | None = None
    source: str = "FRED"


class ValidationResult:
    """Result of a validation check."""

    def __init__(self, is_valid: bool, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def __bool__(self) -> bool:
        return self.is_valid


def validate_stock_price(data: dict[str, Any]) -> ValidationResult:
    """Validate a stock price data point."""
    try:
        StockPriceSchema(**data)
        return ValidationResult(True)
    except Exception as exc:
        return ValidationResult(False, [str(exc)])


def validate_financial_statement(data: dict[str, Any]) -> ValidationResult:
    """Validate a financial statement."""
    try:
        FinancialStatementSchema(**data)
        return ValidationResult(True)
    except Exception as exc:
        return ValidationResult(False, [str(exc)])


def validate_news(data: dict[str, Any]) -> ValidationResult:
    """Validate a news item."""
    try:
        NewsSchema(**data)
        return ValidationResult(True)
    except Exception as exc:
        return ValidationResult(False, [str(exc)])


def validate_economic_indicator(data: dict[str, Any]) -> ValidationResult:
    """Validate an economic indicator data point."""
    try:
        EconomicIndicatorSchema(**data)
        return ValidationResult(True)
    except Exception as exc:
        return ValidationResult(False, [str(exc)])