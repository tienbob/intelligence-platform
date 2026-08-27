"""
Stock domain — ticker symbol validation.

Uses the platform's generic ``validate_identifier`` helper with a
ticker-specific regex pattern.
"""

from __future__ import annotations

from app.core.security import validate_identifier

# Ticker pattern: 1-20 uppercase letters, digits, dots, or hyphens
_TICKER_PATTERN = r"^[A-Z0-9.\-]{1,20}$"


def validate_ticker(ticker: str) -> str:
    """Validate a stock ticker symbol format.

    Accepts uppercase letters, digits, dots, and hyphens (e.g. AAPL, BRK.B, 9988.HK).
    """
    return validate_identifier(ticker, pattern=_TICKER_PATTERN, label="ticker")