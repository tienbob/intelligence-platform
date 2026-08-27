"""
Stock & Investment Intelligence Domain.

This domain pack encapsulates all stock-market-specific logic:
company analysis, financial metrics, technical indicators,
portfolio optimization, investment scoring, and market event detection.
"""

from app.core.security_scan import register_source_reliability

# Register stock-domain source reliability scores.
# These are used by the platform's evidence attribution and data quality
# scoring to weight observations by source trustworthiness.
register_source_reliability({
    "sec": 1.00,
    "regulatory": 1.00,
    "company_ir": 0.95,
    "major_financial_news": 0.90,
    "fmp": 0.90,
    "massive": 0.85,
    "finnhub": 0.80,
})
