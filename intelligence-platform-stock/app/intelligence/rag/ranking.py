"""
Ranking, merging, and deduplication — generic retrieval post-processing.

These operations are pure functions over ``RetrievedDocument`` lists so
they can be unit-tested without a database.
"""

from __future__ import annotations

from app.intelligence.rag.types import RetrievedDocument


def merge_results(
    *result_lists: list[RetrievedDocument],
    prefer_earlier: bool = True,
) -> list[RetrievedDocument]:
    """
    Merge result lists, deduplicating by document id.

    With ``prefer_earlier=True`` (the legacy Stock hybrid-search behavior),
    a document seen in an earlier list is kept as-is even if a later list
    scored it higher. With ``prefer_earlier=False``, the highest score wins.
    """
    merged: dict = {}
    for results in result_lists:
        for doc in results:
            existing = merged.get(doc.id)
            if existing is None:
                merged[doc.id] = doc
            elif not prefer_earlier and doc.score > existing.score:
                merged[doc.id] = doc
    return list(merged.values())


def rank_results(
    documents: list[RetrievedDocument],
    limit: int,
    *,
    tie_break_by_id: bool = False,
) -> list[RetrievedDocument]:
    """
    Sort by score descending and return the top ``limit`` documents.

    ``tie_break_by_id`` gives deterministic ordering when scores tie
    (useful for reproducible tests). When False, Python's stable sort
    preserves insertion order for ties — matching the legacy behavior.
    """
    if tie_break_by_id:
        ordered = sorted(
            documents, key=lambda d: (-d.score, str(d.id)), reverse=False
        )
    else:
        ordered = sorted(documents, key=lambda d: d.score, reverse=True)
    return ordered[:limit]


def deduplicate(documents: list[RetrievedDocument]) -> list[RetrievedDocument]:
    """Remove duplicate ids, keeping the first occurrence."""
    seen: set = set()
    unique: list[RetrievedDocument] = []
    for doc in documents:
        if doc.id not in seen:
            seen.add(doc.id)
            unique.append(doc)
    return unique