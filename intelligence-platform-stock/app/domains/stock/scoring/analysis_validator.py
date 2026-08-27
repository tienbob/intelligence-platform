"""
Stock structured-output validation for AI analysis (Section 31, Section 54).

The generic mechanics (required fields, type checks, confidence bounds,
membership validation) now come from ``app.intelligence.validation``.
This module keeps only Stock-specific *rules*: what counts as a valid
company / risk / portfolio analysis.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.intelligence.validation.types import OutputValidationError

logger = get_logger(__name__)

# Required top-level fields for company analysis output
REQUIRED_COMPANY_ANALYSIS_FIELDS = [
    "summary",
    "market_interpretation",
    "causes",
    "bull_case",
    "bear_case",
    "investment_thesis",
    "confidence",
]

# Required fields for cause/claim items (aligned with prompt output schema)
REQUIRED_CLAIM_FIELDS = [
    "cause",
    "impact",
    "confidence",
]


# Stock-level validation error (re-exported for backward compatibility).
AnalysisValidationError = OutputValidationError


class AnalysisValidator:
    """
    Validates structured LLM output against Stock business rules.

    Delegates generic mechanics (required fields, type checks, bounds)
    to the framework validation core; owns Stock-analysis rules.
    """

    @staticmethod
    def validate_company_analysis(output: dict[str, Any]) -> None:
        """
        Validate company analysis output.

        Raises:
            AnalysisValidationError: If validation fails
        """
        missing = [
            f for f in REQUIRED_COMPANY_ANALYSIS_FIELDS if f not in output
        ]
        if missing:
            raise AnalysisValidationError(f"Missing required fields: {missing}")

        confidence = output.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            raise AnalysisValidationError(f"Invalid confidence: {confidence}")

        causes = output.get("causes", [])
        if not isinstance(causes, list):
            raise AnalysisValidationError("causes must be a list")

        for claim in causes:
            AnalysisValidator._validate_claim(claim)

        # bull_case / bear_case are lists of strings per the
        # company_analysis.txt prompt. Validate they are lists of strings,
        # not claim dicts.
        for field in ("bull_case", "bear_case"):
            items = output.get(field, [])
            if not isinstance(items, list):
                raise AnalysisValidationError(f"{field} must be a list")
            for item in items:
                if not isinstance(item, str):
                    raise AnalysisValidationError(f"{field} items must be strings")

    @staticmethod
    def _validate_claim(claim: dict[str, Any]) -> None:
        """Validate a single claim/cause item."""
        if not isinstance(claim, dict):
            raise AnalysisValidationError("Claim must be a dict")

        missing = [f for f in REQUIRED_CLAIM_FIELDS if f not in claim]
        if missing:
            raise AnalysisValidationError(f"Claim missing fields: {missing}")

        # evidence_ids is optional (prompt doesn't require it); warn if missing
        evidence_ids = claim.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            raise AnalysisValidationError("evidence_ids must be a list")

        if len(evidence_ids) == 0:
            logger.warning("Claim has no evidence attribution: %s", claim.get("cause"))

        impact = claim.get("impact")
        if impact not in {"high", "medium", "low"}:
            raise AnalysisValidationError(f"Invalid claim impact: {impact}")

        confidence = claim.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            raise AnalysisValidationError(f"Invalid claim confidence: {confidence}")

    @staticmethod
    def validate_risk_analysis(output: dict[str, Any]) -> None:
        """Validate risk analysis output (aligned with risk_analysis.txt prompt)."""
        required = ["summary", "overall_risk_level", "risk_factors"]
        missing = [f for f in required if f not in output]
        if missing:
            raise AnalysisValidationError(f"Missing risk fields: {missing}")

        risk_level = output.get("overall_risk_level")
        if risk_level not in {"low", "medium", "high"}:
            raise AnalysisValidationError(f"Invalid overall_risk_level: {risk_level}")

        risk_factors = output.get("risk_factors", [])
        if not isinstance(risk_factors, list):
            raise AnalysisValidationError("risk_factors must be a list")

    @staticmethod
    def validate_portfolio_analysis(output: dict[str, Any]) -> None:
        """Validate portfolio analysis output (aligned with portfolio_analysis.txt prompt)."""
        required = ["summary", "allocation_assessment", "recommendations"]
        missing = [f for f in required if f not in output]
        if missing:
            raise AnalysisValidationError(f"Missing portfolio fields: {missing}")

        recommendations = output.get("recommendations", [])
        if not isinstance(recommendations, list):
            raise AnalysisValidationError("recommendations must be a list")
