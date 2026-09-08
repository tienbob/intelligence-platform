"""
Canonical table-ownership registry (PLAN Gate 4.3, Stage 1 — `FRAMEWORK_OWNED_TABLES` guard).

This module is the **single source of truth** for table classification. It is
pure data (no domain / framework / ORM imports) so it can be consumed by:

* the Stage 1 static migration-ownership guard (`tests/test_migration_ownership_guard.py`)
* the Stage 2 schema-introspection check (`scripts/verify_schema_ownership.py`)
* the registry-doc reconciliation test (`tests/test_table_registry_scope.py`)
* ``docs/TABLE_OWNERSHIP.md`` §4.3 (kept in sync by the reconciliation test)

Five disjoint categories — there is deliberately **no** "everything else"
fallback; a live table not in the union, or present in two categories, is a
failure. See ``docs/TABLE_OWNERSHIP.md`` for the semantic rationale and
writer-scan evidence behind each classification.
"""

from __future__ import annotations

# ── Framework-owned ────────────────────────────────────────────────
# Serves any domain generically. ORM lives in app/intelligence/models/;
# domains consume via the framework contract/injection only.
FRAMEWORK_OWNED_TABLES: frozenset[str] = frozenset({"embeddings"})

# ── Domain-owned: stock ───────────────────────────────────────────
# Models a stock-domain concept. ORM in app/domains/stock/models/.
STOCK_OWNED_TABLES: frozenset[str] = frozenset(
    {
        "alerts",
        "analyses",
        "analysis_sources",
        "anomaly_scores",
        "backtest_ai_evaluations",
        "backtest_benchmarks",
        "backtest_results",
        "backtest_runs",
        "backtest_score_evaluations",
        "backtest_snapshots",
        "backtest_trades",
        "companies",
        "company_news",
        "economic_indicators",
        "event_price_correlations",
        "financial_metrics",
        "financial_statements",
        "investment_scores",
        "market_events",
        "news",
        "raw_macro_data",
        "raw_market_data",
        "raw_news",
        "raw_sec_filings",
        "risk_metrics",
        "sec_filings",
        "stock_prices",
        "technical_indicators",
    }
)

# ── Application-owned ──────────────────────────────────────────────
# Identity / access control. Semantic owner = application/auth layer (Rails
# gateway enforces); DDL provisioned via Alembic because python-migrate is the
# only deployed pipeline. Python reads scope only, never writes.
APPLICATION_OWNED_TABLES: frozenset[str] = frozenset({"users", "user_companies"})

# ── Infrastructure ─────────────────────────────────────────────────
# Owned by tooling (Alembic / Rails bookkeeping); never touched by
# application code. These legitimately persist in any deployed DB, so they
# are classified (not retired) and expected to be present by the schema
# check.
INFRASTRUCTURE_TABLES: frozenset[str] = frozenset(
    {"alembic_version", "schema_migrations", "ar_internal_metadata"}
)

# ── Legacy — retire candidates ─────────────────────────────────────
# No ORM class and zero references in either codebase. Dropped by Alembic
# 0017; must be ABSENT from a fully-migrated DB. Kept here so the schema
# introspection check can assert they are gone (and so the categories stay
# jointly exhaustive). Rails' own bookkeeping tables (schema_migrations,
# ar_internal_metadata) are deliberately NOT here — they persist and are
# classified as infrastructure above.
RETIRE_CANDIDATES: frozenset[str] = frozenset(
    {
        "portfolio_allocation_history",
        "portfolio_drift_alerts",
        "portfolio_holdings",
        "portfolio_rebalance_trades",
        "portfolio_recommendations",
        "portfolios",
    }
)

def all_classified() -> frozenset[str]:
    """Union of the four *active* ownership categories (retirees excluded).

    A table present in a fully-migrated, post-Gate-4 DB must be a member of
    this set. Retire candidates are intentionally NOT included — they should
    have been dropped and their presence is a regression.
    """
    return (
        FRAMEWORK_OWNED_TABLES
        | STOCK_OWNED_TABLES
        | APPLICATION_OWNED_TABLES
        | INFRASTRUCTURE_TABLES
    )


def categories() -> dict[str, frozenset[str]]:
    """The four active categories as a labelled mapping (retirees separate)."""
    return {
        "framework": FRAMEWORK_OWNED_TABLES,
        "stock": STOCK_OWNED_TABLES,
        "application": APPLICATION_OWNED_TABLES,
        "infrastructure": INFRASTRUCTURE_TABLES,
        "retire": RETIRE_CANDIDATES,
    }


def is_disjoint() -> bool:
    """True when no table appears in more than one category (retirees may
    overlap nothing — they are dropped)."""
    sets = list(categories().values())
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            if sets[i] & sets[j]:
                return False
    return True


def classify(table: str) -> str | None:
    """Return the category label for ``table``, or None if unclassified."""
    for label, members in categories().items():
        if table in members:
            return label
    return None