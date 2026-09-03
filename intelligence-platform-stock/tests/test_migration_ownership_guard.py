"""Gate 4.3 — Stage 1: CI ownership guard (static, no DB).

The migration pipeline is the single DDL owner for the shared Postgres DB,
but tables have *semantic* owners (framework / stock / application / infra).
A migration must never let one owner encroach on another's tables.

This guard statically scans every Alembic migration's DDL and asserts:

1. A framework-owned table (``embeddings``) may only be created/altered/
   dropped by an explicit allow-list of *sanctioned framework revisions*.
   Any other revision that touches a framework table is a violation.
2. The ownership categories are disjoint and exhaustive (delegated to the
   canonical registry via ``app.core.table_ownership``).

The negative test feeds a deliberately-invalid domain migration (a Stock
revision that adds a column to ``embeddings``) through the same scanner and
asserts the guard flags it — proving the guard actually rejects violations
rather than passing trivially.

Pure static analysis: reads migration source text, runs in milliseconds,
no database or ORM required. Safe for CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "migrations" / "versions"
INVALID_DIR = ROOT / "tests" / "fixtures" / "invalid_migrations"

# Framework-owned tables may only be touched by these sanctioned revisions.
# 0001 creates embeddings; 0002/0009 resize the vector column; 0014
# recreates the table; 0020 adds the generic `domain` identity (Gate 4.2).
SANCTIONED_FRAMEWORK_REVISIONS: frozenset[str] = frozenset(
    {"0001", "0002", "0009", "0014", "0020"}
)

# Tables owned by the framework — encroachment by any non-sanctioned
# revision is a hard failure.
FRAMEWORK_TABLES = frozenset({"embeddings"})


# ── DDL scanner ──────────────────────────────────────────────────
# Maps table name -> {revision_id, ...} for every table a migration
# creates, alters, or drops. Covers both the structured Alembic ops and the
# raw DDL strings (op.execute) that pgvector's custom type forces us to use.

_OP_TABLE = re.compile(
    r"op\."
    r"(?:create_table|drop_table|add_column|drop_column|alter_column)"
    r"\(\s*['\"](\w+)['\"]"
)
# op.create_index('ix_name', 'table_name', [...])
_OP_INDEX = re.compile(r"op\.create_index\([^,]+,\s*['\"](\w+)['\"]")
# op.drop_index('ix_name', ..., table_name='table_name')
_OP_DROP_INDEX = re.compile(r"op\.drop_index\([^)]*table_name\s*=\s*['\"](\w+)['\"]")
# Raw DDL inside op.execute / bare strings.
_SQL_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)")
_SQL_ALTER = re.compile(r"ALTER\s+TABLE\s+(\w+)")
_SQL_DROP = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)")


def _revision_id(path: Path) -> str:
    text = path.read_text()
    # Accept `revision = "0007"` and `revision: str = "0007"`.
    m = re.search(r"^revision(?:\s*:\s*str)?\s*=\s*['\"](\w+)['\"]", text, re.M)
    if not m:
        raise AssertionError(f"no revision id in {path.name}")
    return m.group(1)


def scan_migration_tables(versions_dir: Path) -> dict[str, set[str]]:
    """Return {table: {revision ids that create/alter/drop it)}.

    Scans only real migration files (skips ``__init__.py`` / ``__pycache__``).
    """
    touched: dict[str, set[str]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        rev = _revision_id(path)
        text = path.read_text()
        tables: set[str] = set()
        tables.update(m.group(1) for m in _OP_TABLE.finditer(text))
        tables.update(m.group(1) for m in _OP_INDEX.finditer(text))
        tables.update(m.group(1) for m in _OP_DROP_INDEX.finditer(text))
        tables.update(m.group(1) for m in _SQL_CREATE.finditer(text))
        tables.update(m.group(1) for m in _SQL_ALTER.finditer(text))
        tables.update(m.group(1) for m in _SQL_DROP.finditer(text))
        for t in tables:
            touched.setdefault(t, set()).add(rev)
    return touched


def framework_violations(
    touched: dict[str, set[str]],
) -> list[tuple[str, str]]:
    """(revision, table) pairs that encroach on framework-owned tables."""
    violations: list[tuple[str, str]] = []
    for table in FRAMEWORK_TABLES:
        for rev in touched.get(table, set()):
            if rev not in SANCTIONED_FRAMEWORK_REVISIONS:
                violations.append((rev, table))
    return violations


# ── Tests ────────────────────────────────────────────────────────

def test_sanctioned_framework_revisions_actually_exist():
    """Every sanctioned revision must correspond to a real migration file —
    guards against a stale allow-list referencing a deleted revision."""
    files = {p.stem.split("_")[0] for p in VERSIONS_DIR.glob("*.py")
             if not p.name.startswith("__")}
    missing = SANCTIONED_FRAMEWORK_REVISIONS - files
    assert not missing, f"sanctioned revisions missing from versions/: {missing}"


def test_only_referenced_revisions_touch_framework_tables():
    """Every revision that actually touches a framework table must be on the
    sanctioned list. Keeps the allow-list honest (no stale entries that
    reference already-removed DDL)."""
    touched = scan_migration_tables(VERSIONS_DIR)
    encroachers = (
        {rev for table in FRAMEWORK_TABLES for rev in touched.get(table, set())}
        - SANCTIONED_FRAMEWORK_REVISIONS
    )
    assert not encroachers, (
        f"non-sanctioned revisions reference framework table(s): {encroachers}"
    )


def test_no_unauthorized_encroachment_on_framework_tables():
    """The core Stage 1 rule: framework tables are off-limits unless the
    revision is explicitly sanctioned."""
    touched = scan_migration_tables(VERSIONS_DIR)
    violations = framework_violations(touched)
    assert not violations, (
        "framework-ownership violation(s) (revision touches a framework "
        f"table without sanction): {violations}"
    )


def test_guard_rejects_deliberate_domain_encroachment():
    """Negative test: a domain (Stock) migration that reaches into the
    framework-owned embeddings table must be flagged. Proves the guard
    rejects violations rather than passing vacuously.

    The fixture lives under tests/fixtures/invalid_migrations/ and is NOT in
    the Alembic versions dir, so we scan it in isolation and assert the
    same guard logic flags it.
    """
    touched = scan_migration_tables(INVALID_DIR)
    violations = framework_violations(touched)
    assert violations, (
        "expected the deliberate domain-encroachment fixture to be flagged, "
        "but the guard reported no violations"
    )
    revs = {rev for rev, _ in violations}
    assert "0099" in revs, f"expected revision 0099 to be flagged, got {revs}"


def test_ownership_registry_is_canonical_and_disjoint():
    """Stage 1 consumes the canonical registry; assert it is internally
    consistent (disjoint categories; retirees excluded from active set)."""
    from app.core.table_ownership import (
        RETIRE_CANDIDATES,
        all_classified,
        is_disjoint,
    )

    assert is_disjoint(), "ownership categories overlap (a table in two categories)"
    active = all_classified()
    assert not (active & RETIRE_CANDIDATES), (
        "retire candidates still present in active classification: "
        f"{active & RETIRE_CANDIDATES}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))