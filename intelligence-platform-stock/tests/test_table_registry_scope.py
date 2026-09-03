"""Gate 4.1 integrity: registry ↔ code + access-scoping (user_companies).

1. docs/TABLE_OWNERSHIP.md is the ownership registry; this test enforces that
   every stock-domain ORM table is actually listed in it and that the doc's
   five-category counts reconcile against the live model inventory — the
   doc cannot silently drift from the schema.
2. Access-scoping helpers behave per the contract (X-User-Id → scoped;
   absent → unscoped; empty grants → zero rows).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.domains.stock.models  # noqa: F401,E402  (registers all tables)
import app.intelligence.models  # noqa: F401,E402  (registers framework tables)
from app.core.database import Base  # noqa: E402
from app.domains.stock.models.company import Company  # noqa: E402
from app.intelligence.models import Embedding  # noqa: E402
from app.shared.identity import (  # noqa: E402
    REQUESTER_HEADER,
    company_is_scoped,
    requester_id_from_headers,
    scope_company_query,
    scoped_where,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "TABLE_OWNERSHIP.md"


# ── Registry ↔ code integrity ───────────────────────────────────

def _doc_categories() -> dict[str, set[str]]:
    text = DOC.read_text()
    cats: dict[str, set[str]] = {}
    section = None
    for line in text.splitlines():
        h = line.strip()
        if h.startswith("### Framework-owned"):
            section = "framework"
        elif h.startswith("### Domain-owned: stock"):
            section = "stock"
        elif h.startswith("### Application-owned"):
            section = "application"
        elif h.startswith("### Legacy"):
            section = "legacy"
        elif h.startswith("### Infrastructure"):
            section = "infrastructure"
        elif h.startswith("### ") or h.startswith("## "):
            section = None
        m = re.match(r"^\|\s*`(\w+)`\s*\|", line)
        if section and m:
            cats.setdefault(section, set()).add(m.group(1))
    return cats


def test_registry_covers_every_stock_model_table():
    cats = _doc_categories()
    live_tables = {t for t in Base.metadata.tables}
    # Remove tables that are not stock-domain ORM tables:
    live_tables -= {"embeddings"}                     # framework (4.2) — see below
    live_tables -= {"users"}                          # application-owned
    live_tables -= {"user_companies"}                 # application-owned
    live_tables -= {"ar_internal_metadata", "schema_migrations"}  # Rails infra
    live_tables -= {f"portfolio_{n}" for n in (
        "allocation_history", "drift_alerts", "holdings",
        "rebalance_trades", "recommendations",
    )} | {"portfolios"}                               # legacy
    assert live_tables <= cats.get("stock", set()), (
        f"Stock ORM tables missing from registry: {live_tables - cats.get('stock', set())}"
    )


def test_embedding_orm_is_registered_but_not_stock_owned():
    """Gate 4.2: the `embeddings` table's ORM is framework-owned. It must be
    registered on Base.metadata (so create_all/migrations know it) but its
    module must live under app/intelligence/models — never stock."""
    assert "embeddings" in Base.metadata.tables
    assert Embedding.__module__.startswith("app.intelligence.models"), (
        f"Embedding ORM must be framework-owned, got {Embedding.__module__}"
    )
    assert "embeddings" not in _doc_categories()["stock"]


def test_registry_counts_reconcile_with_reality():
    cats = _doc_categories()
    # The canonical registry is the source of truth; the doc must match it.
    from app.core.table_ownership import (
        APPLICATION_OWNED_TABLES,
        FRAMEWORK_OWNED_TABLES,
        INFRASTRUCTURE_TABLES,
        RETIRE_CANDIDATES,
        STOCK_OWNED_TABLES,
    )

    assert cats["framework"] == set(FRAMEWORK_OWNED_TABLES)
    assert cats["stock"] == set(STOCK_OWNED_TABLES)
    assert cats["application"] == set(APPLICATION_OWNED_TABLES)
    assert cats["infrastructure"] == set(INFRASTRUCTURE_TABLES)
    assert cats["legacy"] == set(RETIRE_CANDIDATES)
    assert "users" in cats["application"]              # retained, NOT retired
    assert "users" not in cats["legacy"]
    # categories are disjoint
    all_sets = [cats[k] for k in ("framework", "stock", "application", "legacy", "infrastructure")]
    for i in range(len(all_sets)):
        for j in range(i + 1, len(all_sets)):
            assert not (all_sets[i] & all_sets[j]), "table classified twice"


def test_scope_query_compiles_with_junction_filter():
    stmt = scope_company_query(
        __import__("sqlalchemy").select(Company.id), Company, {1, 3}
    )
    sql = str(stmt.compile())
    assert "companies.id in" in sql.lower()


def test_scope_query_unscoped_is_unchanged():
    from sqlalchemy import select

    base = select(Company.id)
    assert str(scope_company_query(base, Company, None).compile()) == str(base.compile())


def test_scope_query_empty_grants_forces_zero_rows():
    from sqlalchemy import select

    stmt = scope_company_query(select(Company.id), Company, set())
    sql = str(stmt.compile())
    # scope_company_query sets id==-1 for the empty-grant set; SQLAlchemy
    # binds it as a param, so we check the bound marker maps id=-1.
    assert "companies.id = :id_1" in sql


def test_requester_header_parsing():
    class H(dict):
        def get(self, k, d=None):
            return super().get(k, d)

    assert requester_id_from_headers({REQUESTER_HEADER: "42"}) == 42
    assert requester_id_from_headers({REQUESTER_HEADER: " 7 "}) == 7
    assert requester_id_from_headers({}) is None
    assert requester_id_from_headers({REQUESTER_HEADER: ""}) is None
    assert requester_id_from_headers({REQUESTER_HEADER: "abc"}) is None


def test_company_is_scoped():
    # Unscoped (None) means everything is visible.
    assert company_is_scoped(5, None) is True
    # Scoped: only granted companies visible.
    assert company_is_scoped(5, {1, 3, 5}) is True
    assert company_is_scoped(5, {1, 3}) is False
    # A company-less row (None) is never visible to a scoped user.
    assert company_is_scoped(None, {1, 3}) is False
    # Empty grants (user with no companies) reveal nothing.
    assert company_is_scoped(5, set()) is False


def test_scoped_where_general_column():
    from sqlalchemy import select

    from app.domains.stock.models.alert import Alert

    base = select(Alert.id)
    bind = scoped_where(base, Alert.company_id, {1, 3})
    sql = str(bind.compile())
    assert "alerts.company_id in" in sql.lower()

    empty = scoped_where(select(Alert.id), Alert.company_id, set())
    assert "alerts.company_id = :company_id_1" in str(empty.compile())

    # Unscoped leaves the query unchanged.
    assert str(scoped_where(base, Alert.company_id, None).compile()) == str(base.compile())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("REGISTRY + SCOPE TESTS PASS")
