"""
Metadata filter SQL construction — generic, provider- and domain-neutral.

Builds WHERE-clause fragments against the ``embeddings`` table from a
``RetrievalFilters`` object. Used by both vector and keyword search so
the two retrieval modes always apply identical constraints.
"""

from __future__ import annotations

from typing import Any

from app.intelligence.rag.types import RetrievalFilters


def build_filter_sql(
    filters: RetrievalFilters | None,
    *,
    param_offset: int = 0,
) -> tuple[str, dict[str, Any]]:
    """
    Build the SQL fragment (starting with " AND") plus bound params for
    the given filters. Returns ("", {}) when no filters are set.

    ``param_offset`` shifts generated placeholder indices so callers can
    combine this fragment with their own numbered placeholders.
    """
    if filters is None or filters.is_empty():
        return "", {}

    sql_parts: list[str] = []
    params: dict[str, Any] = {}
    i = param_offset

    for domain in filters.domains:
        sql_parts.append(f"domain = :f_dom_{i}")
        params[f"f_dom_{i}"] = domain
        i += 1

    for entity_type in filters.entity_types:
        sql_parts.append(f"entity_type = :f_type_{i}")
        params[f"f_type_{i}"] = entity_type
        i += 1

    for key, value in filters.metadata_equals.items():
        sql_parts.append(f"(metadata->>'{key}') = :f_eq_{i}")
        params[f"f_eq_{i}"] = str(value)
        i += 1

    for key, minimum in filters.metadata_min.items():
        # Missing metadata counts as 0 (mirrors the legacy COALESCE form).
        sql_parts.append(f"COALESCE((metadata->>'{key}')::float, 0) >= :f_min_{i}")
        params[f"f_min_{i}"] = float(minimum)
        i += 1

    date_field = filters.date_metadata_field
    if filters.date_from is not None:
        sql_parts.append(f"(metadata->>'{date_field}') >= :f_from_{i}")
        params[f"f_from_{i}"] = filters.date_from.isoformat()
        i += 1
    if filters.date_to is not None:
        sql_parts.append(f"(metadata->>'{date_field}') <= :f_to_{i}")
        params[f"f_to_{i}"] = filters.date_to.isoformat()
        i += 1

    if not sql_parts:
        return "", {}
    return " AND " + " AND ".join(sql_parts), params