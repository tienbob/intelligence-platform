"""
Generic validation core — the framework's structured-output validator.

The framework owns how outputs are validated (required fields, type
checks, confidence bounds, membership, schema conformance, repair).
Domains own what schemas and rules apply to their analysis.
"""

from app.intelligence.validation.schema import (
    collect,
    require_fields,
    require_list,
    require_list_of,
    require_list_of_dict,
    validate_confidence,
    validate_in,
)
from app.intelligence.validation.service import SchemaValidator, ValidationService
from app.intelligence.validation.types import (
    OutputValidationError,
    ValidationIssue,
    ValidationResult,
)

__all__ = [
    "OutputValidationError",
    "SchemaValidator",
    "ValidationIssue",
    "ValidationResult",
    "ValidationService",
    "collect",
    "require_fields",
    "require_list",
    "require_list_of",
    "require_list_of_dict",
    "validate_confidence",
    "validate_in",
]