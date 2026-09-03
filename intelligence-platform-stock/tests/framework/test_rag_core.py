"""
Framework tests: generic RAG core.

Tests use SYNTHETIC documents and a fake in-memory vector store — no
database required. They verify the generic mechanics that Stock (and any
future domain) now depends on:

    similarity ordering, thresholds, limits, entity/metadata filtering,
    deduplication, merge preference, empty results, malformed metadata,
    deterministic ordering for equal scores.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.rag import (  # noqa: E402
    RetrievedDocument,
    RetrievalFilters,
    build_filter_sql,
    deduplicate,
    merge_results,
    rank_results,
)


def run(coro):
    return asyncio.run(coro)


def doc(id_, score, entity_type="news", metadata=None):
    return RetrievedDocument(
        id=id_, content=f"content-{id_}", score=score,
        entity_type=entity_type, metadata=metadata or {},
    )


# ── Ranking ─────────────────────────────────────────────────────

def test_ranking_orders_by_score_desc_and_limits():
    docs = [doc(i, s) for i, s in enumerate([0.9, 0.5, 0.7, 0.3])]
    top = rank_results(docs, 2)
    assert [d.id for d in top] == [0, 2]
    assert top[0].score == 0.9


def test_ranking_limit_larger_than_input():
    assert len(rank_results([doc(1, 0.5)], 10)) == 1


def test_ranking_deterministic_for_equal_scores():
    docs = [doc("b", 0.5), doc("a", 0.5), doc("c", 0.5)]
    first = rank_results(list(reversed(docs)), 3, tie_break_by_id=True)
    second = rank_results(docs, 3, tie_break_by_id=True)
    assert [d.id for d in first] == [d.id for d in second] == ["a", "b", "c"]


def test_deduplicate_keeps_first_occurrence():
    out = deduplicate([doc(1, 0.9), doc(2, 0.8), doc(1, 0.99)])
    assert [d.id for d in out] == [1, 2]


def test_merge_prefers_earlier_list_on_collision():
    semantic = [doc(1, 0.6)]
    keyword = [doc(1, 0.95), doc(2, 0.4)]
    merged = merge_results(semantic, keyword, prefer_earlier=True)
    by_id = {d.id: d for d in merged}
    assert by_id[1].score == 0.6  # semantic hit preserved despite lower score
    assert by_id[2].score == 0.4


def test_merge_highest_score_wins_when_not_preferring_earlier():
    semantic = [doc(1, 0.6)]
    keyword = [doc(1, 0.95)]
    merged = merge_results(semantic, keyword, prefer_earlier=False)
    assert merged[0].score == 0.95


# ── Filters ─────────────────────────────────────────────────────

def test_empty_filters_produce_no_sql():
    sql, params = build_filter_sql(RetrievalFilters())
    assert sql == "" and params == {}
    sql, params = build_filter_sql(None)
    assert sql == "" and params == {}


def test_entity_type_and_metadata_filters_build_sql():
    filters = RetrievalFilters(
        entity_types=["news"],
        metadata_equals={"company_id": "123"},
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    sql, params = build_filter_sql(filters)
    assert "entity_type = :f_type_0" in sql
    assert "(metadata->>'company_id') = :f_eq_1" in sql
    assert params["f_type_0"] == "news"
    assert params["f_eq_1"] == "123"
    assert params["f_from_2"] == "2026-01-01T00:00:00+00:00"


def test_numeric_min_filter_uses_coalesce():
    sql, params = build_filter_sql(
        RetrievalFilters(metadata_min={"importance": 0.5})
    )
    assert "COALESCE((metadata->>'importance')::float, 0) >= :f_min_0" in sql
    assert params["f_min_0"] == 0.5


# ── Result types / legacy shape compatibility ───────────────────

def test_legacy_dict_roundtrip():
    d = doc(7, 0.88, metadata={"company_id": "123"})
    d.domain = "stock"
    legacy = d.to_legacy_dict()
    assert set(legacy) == {"id", "domain", "entity_type", "entity_id", "content",
                           "metadata", "similarity"}
    back = RetrievedDocument.from_legacy_dict(legacy)
    assert back.id == d.id and back.score == 0.88
    assert back.domain == "stock"


def test_domain_filter_builds_sql():
    sql, params = build_filter_sql(RetrievalFilters(domains=["stock"]))
    assert "domain = :f_dom_0" in sql
    assert params["f_dom_0"] == "stock"

    sql2, params2 = build_filter_sql(
        RetrievalFilters(domains=["stock"], entity_types=["news"])
    )
    assert "domain = :f_dom_0" in sql2 and "entity_type = :f_type_1" in sql2


def test_domain_filter_makes_filters_non_empty():
    assert RetrievalFilters().is_empty() is True
    assert RetrievalFilters(domains=["stock"]).is_empty() is False


def test_malformed_metadata_tolerated():
    # None / non-dict metadata must not crash conversion or ranking
    d = RetrievedDocument(id=1, content="x", score=0.5, metadata=None)
    ranked = rank_results([d], 1)
    assert ranked[0].metadata == {}
    roundtrip = RetrievedDocument.from_legacy_dict(d.to_legacy_dict())
    assert roundtrip.metadata == {}


def test_empty_result_set():
    assert rank_results([], 5) == []
    assert deduplicate([]) == []
    assert merge_results([], []) == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)