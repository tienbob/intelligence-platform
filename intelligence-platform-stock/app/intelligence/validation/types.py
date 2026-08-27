"""
Validation core types — domain-neutral validation primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class OutputValidationError(Exception):
    """Raised when structured output fails validation."""


@dataclass
class ValidationIssue:
    """A single validation finding."""

    field: str | None
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationResult:
    """The outcome of validating an output."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def error_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.severity == "error"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.is_valid,
            "issues": [i.__dict__ for i in self.issues],
        }