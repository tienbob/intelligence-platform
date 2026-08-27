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
    assert VectorRecord("news", 1, "hi").is_embedded() is False
    rec = VectorRecord("news", 1, "hi", vector=[0.1])
    assert rec.is_embedded() is True


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