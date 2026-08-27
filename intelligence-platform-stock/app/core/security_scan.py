"""
Security scanning (Phase 8, Section 131-134).

Implements:
- Input validation for common injection vectors
- Prompt injection defense helpers
- Data poisoning detection
- Source reliability scoring
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# SQL injection patterns
SQL_INJECTION_PATTERNS = [
    r"(\bSELECT\b.*\bFROM\b)",
    r"(\bINSERT\b.*\bINTO\b)",
    r"(\bUPDATE\b.*\bSET\b)",
    r"(\bDELETE\b.*\bFROM\b)",
    r"(\bDROP\b.*\bTABLE\b)",
    r"(\bUNION\b.*\bSELECT\b)",
    r"(--\s)",
    r"(;\s*DROP\s)",
]

# Prompt injection patterns
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|directions)",
    r"system\s+prompt",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+",
    r"disregard\s+(all\s+)?(previous|prior)\s+",
    r"forget\s+(all\s+)?(previous|prior)\s+",
    r"new\s+instructions",
    r"override\s+(all\s+)?(instructions|rules)",
]

# XSS patterns
XSS_PATTERNS = [
    r"(<script[^>]*>)",
    r"(javascript:)",
    r"(onerror\s*=)",
    r"(onload\s*=)",
]


class SecurityScanner:
    """Scans untrusted input for common security threats."""

    @staticmethod
    def check_sql_injection(text: str) -> list[str]:
        """Check for SQL injection patterns in untrusted input."""
        matches = []
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(pattern)
        return matches

    @staticmethod
    def check_prompt_injection(text: str) -> list[str]:
        """Check for prompt injection patterns in untrusted content (Section 132)."""
        matches = []
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(pattern)
        return matches

    @staticmethod
    def check_xss(text: str) -> list[str]:
        """Check for XSS patterns in untrusted input."""
        matches = []
        for pattern in XSS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(pattern)
        return matches

    @staticmethod
    def scan(text: str) -> dict[str, list[str]]:
        """Run all security checks on untrusted input."""
        return {
            "sql_injection": SecurityScanner.check_sql_injection(text),
            "prompt_injection": SecurityScanner.check_prompt_injection(text),
            "xss": SecurityScanner.check_xss(text),
        }

    @staticmethod
    def is_safe(text: str) -> bool:
        """Return True if no security threats detected."""
        result = SecurityScanner.scan(text)
        return not any(result.values())


# Source reliability is domain-specific. Each domain registers its own
# reliability scores via ``register_source_reliability()``. The core
# provides a default fallback of 0.50 for unknown sources.
#
# Usage from a domain:
#     from app.core.security_scan import register_source_reliability
#     register_source_reliability({
#         "sec": 1.00,
#         "fmp": 0.90,
#     })

_source_reliability: dict[str, float] = {}
_DEFAULT_RELIABILITY: float = 0.50


def register_source_reliability(scores: dict[str, float]) -> None:
    """Register domain-specific source reliability scores.

    Called by domain modules at import time. Later registrations
    override earlier ones for the same source key.
    """
    _source_reliability.update(scores)


def get_source_reliability(source: str) -> float:
    """Get the reliability score for a data source.

    Returns the registered score for the source, or the default (0.50)
    if no domain has registered a score for it.
    """
    source_lower = source.lower()
    for key, score in _source_reliability.items():
        if key in source_lower:
            return score
    return _DEFAULT_RELIABILITY


def sanitize_news_content(content: str) -> str:
    """
    Sanitize untrusted news content before it enters the RAG pipeline.

    - Strips HTML tags
    - Removes script/iframe elements
    - Limits content length
    """
    # Remove script/style blocks
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    content = re.sub(r"<[^>]+>", " ", content)
    # Collapse whitespace
    content = re.sub(r"\s+", " ", content).strip()
    # Limit length
    return content[:10000]