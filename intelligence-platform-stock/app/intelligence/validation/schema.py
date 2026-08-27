"""
Generic schema validation primitives.

Domain-neutral field/type/bounds/membership checks. Any domain composes
these into its own analysis-specific validators.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.intelligence.validation.types import ValidationIssue


def require_fields(
    output: dict[str, Any],
    required: Iterable[str],
    *,
    prefix: str = "",
) -> list[ValidationIssue]:
    """Issue an error for each missing required field."""
    issues = []
    for name in required:
        if name not in output:
            issues.append(
                ValidationIssue(
                    field=f"{prefix}{name}" if prefix else name,
                    message=f"missing required field: {name}",
                )
            )
    return issues


def require_list(
    output: dict[str, Any],
    field_name: str,
    *,
    prefix: str = "",
) -> list[ValidationIssue]:
    """Ensure a field is a list if present."""
    value = output.get(field_name)
    if value is not None and not isinstance(value, list):
        return [
            ValidationIssue(
                field=f"{prefix}{field_name}" if prefix else field_name,
                message=f"{field_name} must be a list",
            )
        ]
    return []


def validate_confidence(
    value: Any,
    *,
    field_name: str = "confidence",
    prefix: str = "",
) -> list[ValidationIssue]:
    """Ensure confidence is within [0, 1]."""
    if value is None:
        return []
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return [
            ValidationIssue(
                field=f"{prefix}{field_name}" if prefix else field_name,
                message=f"{field_name} is not numeric: {value!r}",
            )
        ]
    if not (0.0 <= numeric <= 1.0):
        return [
            ValidationIssue(
                field=f"{prefix}{field_name}" if prefix else field_name,
                message=f"{field_name} out of range: {value!r}",
            )
        ]
    return []


def validate_in(
    value: Any,
    allowed: set,
    *,
    field_name: str,
    prefix: str = "",
) -> list[ValidationIssue]:
    """Ensure value is a member of ``allowed``."""
    if value not in allowed:
        return [
            ValidationIssue(
                field=f"{prefix}{field_name}" if prefix else field_name,
                message=f"invalid {field_name}: {value!r} (expected one of {sorted(allowed)})",
            )
        ]
    return []


def require_list_of(
    output: dict[str, Any],
    field_name: str,
    item_type: type,
    *,
    prefix: str = "",
) -> list[ValidationIssue]:
    """Ensure ``field_name`` is a list whose items are of ``item_type``."""
    issues = require_list(output, field_name, prefix=prefix)
    if issues:
        return issues
    value = output.get(field_name)
    if value is None:
        return []
    for item in value:
        if not isinstance(item, item_type):
            issues.append(
                ValidationIssue(
                    field=f"{prefix}{field_name}" if prefix else field_name,
                    message=f"{field_name} items must be {item_type.__name__}",
                )
            )
    return issues


def require_list_of_dict(output: dict[str, Any], field_name: str, *, prefix: str = "") -> list[ValidationIssue]:
    return require_list_of(output, field_name, dict, prefix=prefix)


def collect(field_sets: list[list[ValidationIssue]]) -> list[ValidationIssue]:
    """Flatten lists of issues into a single list."""
    return [issue for group in field_sets for issue in group]