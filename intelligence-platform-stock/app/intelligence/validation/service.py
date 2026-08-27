"""
Validation service — generic structural validation + schema checking.

Adapts the original Phase-1 ``ValidationService`` (repair-style generic
validation) and adds a generic ``SchemaValidator`` for declarative
schema conformance. Domains supply the expected schema; the framework
checks conformance.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.intelligence.validation.types import (
    ValidationIssue,
    ValidationResult,
)

logger = get_logger(__name__)


class SchemaValidator:
    """
    Declarative schema conformance.

    ``expected_schema`` maps field name → type tag from
    {"str", "list", "dict", "float", "int", "number"}. Returns a
    ValidationResult (tuple-compatible via ``error_messages()`` for the
    legacy (is_valid, issues) niche).
    """

    _TYPE_CHECKS = {
        "str": lambda v: isinstance(v, str),
        "list": lambda v: isinstance(v, list),
        "dict": lambda v: isinstance(v, dict),
        "float": lambda v: isinstance(v, (int, float)),
        "int": lambda v: isinstance(v, int),
        "number": lambda v: isinstance(v, (int, float)),
    }

    def validate(
        self,
        output: dict[str, Any],
        expected_schema: dict[str, str],
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        for field, type_tag in expected_schema.items():
            if field not in output:
                issues.append(
                    ValidationIssue(field, f"missing field: {field}")
                )
                continue
            value = output[field]
            check = self._TYPE_CHECKS.get(type_tag)
            if check is None:
                issues.append(ValidationIssue(field, f"unknown type tag: {type_tag}"))
            elif not check(value):
                issues.append(
                    ValidationIssue(
                        field,
                        f"field '{field}' expected {type_tag}, got {type(value).__name__}",
                    )
                )
        return ValidationResult(issues=issues)


class ValidationService:
    """
    Generic structural validation with repair.

    Ensures required fields exist, coerces list fields, and attaches
    validation metadata. Mirrors the original generic ValidationService.
    """

    _REQUIRED = {"summary"}
    _LIST_FIELDS = ("insights", "risks")

    async def validate(
        self,
        llm_output: Any,
        domain: str = "",
        analysis_type: str = "comprehensive",
    ) -> dict[str, Any]:
        if not isinstance(llm_output, dict):
            logger.warning(
                "LLM output is not a dict (got %s) — wrapping",
                type(llm_output).__name__,
            )
            return {
                "summary": str(llm_output),
                "insights": [],
                "risks": [],
                "_validation": {
                    "status": "wrapped",
                    "original_type": type(llm_output).__name__,
                },
            }

        result = dict(llm_output)
        issues: list[str] = []

        for field in self._REQUIRED:
            if field not in result or not result[field]:
                issues.append(f"missing required field: {field}")
                result[field] = f"No {field} provided by LLM"

        for field in self._LIST_FIELDS:
            if field in result and not isinstance(result[field], list):
                issues.append(f"field '{field}' is not a list — converting")
                result[field] = [result[field]] if result[field] else []
            if field not in result:
                result[field] = []

        result["_validation"] = {
            "status": "valid" if not issues else "repaired",
            "issues": issues,
            "domain": domain,
            "analysis_type": analysis_type,
        }
        return result

    async def validate_schema(
        self,
        llm_output: dict[str, Any],
        expected_schema: dict[str, str],
    ) -> tuple[bool, list[str]]:
        """Validate against a declarative schema; return (is_valid, issues)."""
        validator = SchemaValidator()
        result: ValidationResult = validator.validate(llm_output, expected_schema)
        return result.is_valid, result.error_messages()