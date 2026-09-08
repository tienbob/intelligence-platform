"""
Generic retrieval filter -> SQL compiler.

This module converts framework-level ``RetrievalFilters`` into parameterized
PostgreSQL predicates.

The retrieval layer is domain-agnostic.

Domain-specific identifiers such as:

    company_id
    ticker
    candidate_id

are represented through JSONB metadata rather than hard-coded SQL columns.

Supported filters
-----------------

Generic columns:

    domain
    entity_type

JSONB metadata:

    scalar equality:
        metadata_equals={"company_id": 123}

    numeric minimum:
        metadata_min={"importance": 0.5}

    array membership:
        metadata_contains={"company_ids": [123, 456]}

Date filtering:

    date_from
    date_to

Collections use OR semantics internally:

    domains=["stock", "hr"]

becomes:

    domain IN ('stock', 'hr')

while different filter categories remain ANDed:

    domain IN (...)
    AND entity_type IN (...)
    AND metadata...
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.intelligence.rag.types import RetrievalFilters


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_METADATA_KEY_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


def _validate_metadata_key(key: str) -> str:
    """
    Validate a JSONB metadata key before interpolating it into SQL.

    Values are always passed as bound parameters.

    PostgreSQL does not allow a JSON key used in ``metadata->>'key'`` to be
    supplied as a normal bind parameter, so keys must be validated separately.
    """
    if not isinstance(key, str):
        raise ValueError(
            f"Metadata key must be a string, got {type(key).__name__}."
        )

    if not _METADATA_KEY_RE.fullmatch(key):
        raise ValueError(
            f"Invalid metadata key: {key!r}"
        )

    return key


def _validate_collection(
    values: list[Any] | tuple[Any, ...] | None,
    *,
    name: str,
) -> list[Any]:
    """
    Normalize a filter collection.

    Empty collections are treated as no filter rather than producing invalid
    SQL such as ``IN ()``.
    """
    if values is None:
        return []

    if not isinstance(values, (list, tuple)):
        raise ValueError(
            f"{name} must be a list or tuple."
        )

    return list(values)


def _validate_number(
    value: Any,
    *,
    name: str,
) -> float:
    """
    Convert a numeric filter to float and reject NaN / infinity.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be numeric; got {value!r}."
        ) from exc

    if not math.isfinite(number):
        raise ValueError(
            f"{name} must be finite; got {value!r}."
        )

    return number


# ---------------------------------------------------------------------------
# SQL compiler
# ---------------------------------------------------------------------------

def build_filter_sql(
    filters: RetrievalFilters | None,
    *,
    param_offset: int = 0,
) -> tuple[str, dict[str, Any]]:
    """
    Compile ``RetrievalFilters`` into a SQL predicate and bound parameters.

    Returns:

        (
            " AND ...",
            {"parameter_name": value}
        )

    The returned SQL fragment is intended to be appended to a query that
    already contains its own base WHERE clause.

    Example:

        SELECT ...
        FROM embeddings
        WHERE similarity > :threshold
        <returned SQL fragment>

    Semantics
    ---------

    Same-category collections use OR semantics through ``IN``.

        domains=["stock", "hr"]

        -> domain IN (:f_dom_0, :f_dom_1)

        entity_types=["news", "event"]

        -> entity_type IN (:f_type_2, :f_type_3)

    Different filter categories are ANDed.

        domain IN (...)
        AND entity_type IN (...)
        AND metadata...
    """
    if filters is None or filters.is_empty():
        return "", {}

    if param_offset < 0:
        raise ValueError(
            "param_offset must be greater than or equal to zero."
        )

    sql_parts: list[str] = []
    params: dict[str, Any] = {}
    i = param_offset

    # ------------------------------------------------------------------
    # Domain collection
    # ------------------------------------------------------------------

    domains = _validate_collection(
        filters.domains,
        name="filters.domains",
    )

    domains = [
        str(domain).strip()
        for domain in domains
        if domain is not None and str(domain).strip()
    ]

    if domains:
        placeholders: list[str] = []

        for domain in domains:
            name = f"f_dom_{i}"
            placeholders.append(f":{name}")
            params[name] = domain
            i += 1

        sql_parts.append(
            f"domain IN ({', '.join(placeholders)})"
        )

    # ------------------------------------------------------------------
    # Entity type collection
    # ------------------------------------------------------------------

    entity_types = _validate_collection(
        filters.entity_types,
        name="filters.entity_types",
    )

    entity_types = [
        str(entity_type).strip()
        for entity_type in entity_types
        if (
            entity_type is not None
            and str(entity_type).strip()
        )
    ]

    if entity_types:
        placeholders = []

        for entity_type in entity_types:
            name = f"f_type_{i}"
            placeholders.append(f":{name}")
            params[name] = entity_type
            i += 1

        sql_parts.append(
            f"entity_type IN ({', '.join(placeholders)})"
        )

    # ------------------------------------------------------------------
    # Scalar JSONB metadata equality
    #
    # Example:
    #
    #   metadata_equals={"company_id": 123}
    #
    # becomes:
    #
    #   (metadata->>'company_id') = :f_eq_0
    # ------------------------------------------------------------------

    metadata_equals = (
        filters.metadata_equals or {}
    )

    if not isinstance(metadata_equals, dict):
        raise ValueError(
            "filters.metadata_equals must be a dictionary."
        )

    for raw_key, value in metadata_equals.items():
        key = _validate_metadata_key(raw_key)

        name = f"f_eq_{i}"

        sql_parts.append(
            f"(metadata->>'{key}') = :{name}"
        )

        params[name] = str(value)
        i += 1

    # ------------------------------------------------------------------
    # Numeric metadata minimum
    #
    # Safely ignores malformed/non-numeric JSON values instead of crashing
    # the entire retrieval query.
    #
    # Example:
    #
    #   importance >= 0.5
    # ------------------------------------------------------------------

    metadata_min = (
        filters.metadata_min or {}
    )

    if not isinstance(metadata_min, dict):
        raise ValueError(
            "filters.metadata_min must be a dictionary."
        )

    for raw_key, minimum in metadata_min.items():
        key = _validate_metadata_key(raw_key)

        minimum_value = _validate_number(
            minimum,
            name=f"metadata_min[{key}]",
        )

        name = f"f_min_{i}"

        # PostgreSQL JSONB values are text. A regex guard prevents values such
        # as "N/A" from causing an invalid ::float cast.
        sql_parts.append(
            f"""
            (
                CASE
                    WHEN (metadata->>'{key}')
                         ~ '^[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?$'
                    THEN (metadata->>'{key}')::double precision
                    ELSE NULL
                END
            ) >= :{name}
            """.strip()
        )

        params[name] = minimum_value
        i += 1

    # ------------------------------------------------------------------
    # JSONB array containment
    #
    # This is important for records such as stock news that may belong to
    # multiple companies:
    #
    #   metadata:
    #       {
    #           "company_id": 123,
    #           "company_ids": [123, 456],
    #           "tickers": ["MSFT", "OPENAI"]
    #       }
    #
    # Example:
    #
    #   metadata_contains={"company_ids": [123]}
    #
    # becomes JSONB containment:
    #
    #   metadata @> '{"company_ids": [123]}'
    #
    # No stock-specific knowledge exists here.
    # ------------------------------------------------------------------

    metadata_contains = getattr(
        filters,
        "metadata_contains",
        None,
    ) or {}

    if not isinstance(metadata_contains, dict):
        raise ValueError(
            "filters.metadata_contains must be a dictionary."
        )

    for raw_key, expected in metadata_contains.items():
        key = _validate_metadata_key(raw_key)

        if not isinstance(expected, (list, tuple)):
            raise ValueError(
                f"metadata_contains[{key!r}] must be a list or tuple."
            )

        name = f"f_contains_{i}"

        # Use json.dumps rather than manually constructing JSON so strings,
        # numbers, booleans, etc. are encoded correctly.
        import json

        payload = json.dumps(
            {key: list(expected)}
        )

        sql_parts.append(
            f"metadata @> CAST(:{name} AS jsonb)"
        )

        params[name] = payload
        i += 1

    # ------------------------------------------------------------------
    # Date metadata field
    # ------------------------------------------------------------------

    date_field = _validate_metadata_key(
        filters.date_metadata_field
    )

    # ------------------------------------------------------------------
    # Date lower bound
    # ------------------------------------------------------------------

    if filters.date_from is not None:
        name = f"f_from_{i}"

        sql_parts.append(
            f"(metadata->>'{date_field}') >= :{name}"
        )

        params[name] = filters.date_from.isoformat()
        i += 1

    # ------------------------------------------------------------------
    # Date upper bound
    # ------------------------------------------------------------------

    if filters.date_to is not None:
        name = f"f_to_{i}"

        sql_parts.append(
            f"(metadata->>'{date_field}') <= :{name}"
        )

        params[name] = filters.date_to.isoformat()
        i += 1

    # ------------------------------------------------------------------
    # Final result
    # ------------------------------------------------------------------

    if not sql_parts:
        return "", {}

    return (
        " AND " + " AND ".join(sql_parts),
        params,
    )