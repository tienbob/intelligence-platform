"""
Framework tests: generic embedding core.

Verifies the generic embedding mechanics Stock (and any future domain)
now shares — batching with per-item fallback, chunking, pgvector
conversion + dimension validation, and dedup filters. Tests use
synthetic/fake primitives; no provider calls and no database.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.embeddings import (  # noqa: E402
    VectorRecord,
    chunked,
    embed_batch_with_fallback,
    to_pgvector,
)


def run(coro):
    return asyncio.run(coro)


async def _idem(items):
    """Fake embed_many returning a distinct vector per item."""
    return [[float(x + i)] for i, x in enumerate(items)] if items else []


async def _idem_one(item):
    return [777.0]


# ── Chunking ────────────────────────────────────────────────────

def test_chunked_splits_evenly():
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunked_empty_and_bad_size():
    assert chunked([], 2) == []
    try:
        chunked([1], 0)
        assert False, "should raise"
    except ValueError:
        pass


# ── Batch with fallback ─────────────────────────────────────────

def test_batch_aligns_vectors_to_items():
    async def embed_many(items):
        return [[float(i)] for i in range(len(items))]

    result = run(embed_batch_with_fallback(
        ["a", "b", "c"], embed_one=_idem_one, embed_many=embed_many,
    ))
    assert result == [[0.0], [1.0], [2.0]]


def test_batch_fallback_to_per_item_on_failure():
    calls = {"count": 0}

    async def embed_many(items):
        calls["count"] += 1
        raise RuntimeError("provider down")

    result = run(embed_batch_with_fallback(
        ["a", "b"], embed_one=_idem_one, embed_many=embed_many,
    ))
    assert result == [[777.0], [777.0]]


def test_batch_isolates_single_item_failure():
    async def embed_one(item):
        raise RuntimeError(f"bad: {item}")

    async def embed_many(items):
        raise RuntimeError("provider down")

    result = run(embed_batch_with_fallback(
        ["x", "y"], embed_one=embed_one, embed_many=embed_many,
    ))
    assert result == [[], []]  # failed items yield empty vectors


def test_batch_mismatched_lengths_triggers_fallback():
    async def embed_many(items):
        return [[]]  # wrong count

    result = run(embed_batch_with_fallback(
        ["a", "b"], embed_one=_idem_one, embed_many=embed_many,
    ))
    assert result == [[777.0], [777.0]]


def test_batch_empty_alignment_length():
    async def embed_many(items):
        return [[float(i)] for i in range(len(items))]

    result = run(embed_batch_with_fallback(
        ["a"], embed_one=_idem_one, embed_many=embed_many, chunk_size=1,
    ))
    assert len(result) == 1


# ── Vector conversion + dimension validation ────────────────────

def test_to_pgvector_returns_vector_and_preserves_dims():
    vec = to_pgvector([0.1, 0.2, 0.3], 3)
    assert vec.dimensions() == 3


def test_to_pgvector_raises_on_dimension_mismatch():
    try:
        to_pgvector([0.1, 0.2], 3)
        assert False, "should raise"
    except ValueError as exc:
        assert "2 dimensions" in str(exc)


# ── VectorRecord ────────────────────────────────────────────────

def test_vector_record_is_embedded_flag():
    assert VectorRecord("stock", "news", 1, "hi").is_embedded() is False
    rec = VectorRecord("stock", "news", 1, "hi", vector=[0.1])
    assert rec.is_embedded() is True


def test_vector_record_carries_generic_identity():
    rec = VectorRecord(
        domain="stock",
        entity_type="news",
        entity_id=42,
        content="Apple reports quarterly earnings",
        metadata={"company_id": 7},
    )
    assert rec.domain == "stock"
    assert rec.entity_type == "news"
    assert rec.entity_id == 42


# ── Framework-owned Embedding ORM (Gate 4.2) ─────────────────────

def test_embedding_orm_is_framework_owned():
    """The embeddings table's ORM must live in app.intelligence.models."""
    from app.intelligence.models import Embedding

    assert Embedding.__module__.startswith("app.intelligence.models"), (
        f"Embedding ORM lives in {Embedding.__module__} — must be framework-owned "
        "(app/intelligence/models/) since Gate 4.2"
    )
    assert Embedding.__tablename__ == "embeddings"


def test_embedding_orm_has_generic_identity_columns():
    """Generic identity = (domain, entity_type, entity_id); domain-specific
    columns like company_id/ticker are forbidden on the framework table."""
    from app.intelligence.models import Embedding

    cols = {c.key for c in Embedding.__table__.columns}
    for required in ("domain", "entity_type", "entity_id", "content", "embedding"):
        assert required in cols, f"missing identity column {required}"
    for forbidden in ("company_id", "ticker", "candidate_id"):
        assert forbidden not in cols, (
            f"domain-specific column {forbidden!r} leaked onto framework table"
        )
    assert Embedding.__table__.c.domain.nullable is False
    assert Embedding.__table__.c.domain.type.length == 50


def test_pgvector_store_defaults_to_framework_model():
    """Domains consume the embeddings table via the framework contract:
    PgVectorStore() resolves to the framework-owned Embedding ORM, never a
    domain-injected model."""
    from app.intelligence.embeddings import PgVectorStore
    from app.intelligence.models import Embedding

    store = PgVectorStore()
    assert store.model is Embedding
    assert store.dimensions > 0
    assert store.default_model_name
    # dimensions must be the platform-wide 3072 (vector(3072) in the DB) —
    # the stale 1536 default was removed in Gate 4.2 (stock config).
    assert store.dimensions == 3072, f"unexpected dims: {store.dimensions}"


def test_unembedded_filter_scopes_by_domain():
    """Dedup gate must scope on the full generic identity (domain,
    entity_type, entity_id), not entity_type alone."""
    from app.intelligence.embeddings import Embedding, unembedded_filter
    from app.domains.stock.models.news import News

    filt = unembedded_filter(Embedding, News, entity_type="news", domain="stock")
    sql = f"{filt}"

    assert "domain" in sql
    assert "entity_type" in sql
    assert "entity_id" in sql
    assert "news.id" in sql or "news_1.id" in sql


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