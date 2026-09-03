"""retire deprecated portfolio tables

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-27

Drop ALL six portfolio tables created across migrations 0001 (portfolios,
portfolio_holdings, portfolio_recommendations) and 0008 (portfolio_allocation_history,
portfolio_rebalance_trades, portfolio_drift_alerts) — not "three satellites".
Use this migration ONLY if Step 0 in MIGRATION_FIX_PLAN.md confirms `portfolios`
and all five satellite tables are unused (0 rows, no ORM model in either
service, per docs/TABLE_OWNERSHIP.md). If any are still in use, use the
Option-B variant (0017_add_user_id_to_portfolios.py) instead — not both.

Dropping `portfolios` also resolves the 5.1 circular FK: Rails migration
R2 (db/migrate/20260810024236_add_user_id_to_portfolios.rb) added a FK
constraint *on* portfolios pointing to users. That constraint is owned by
the portfolios table, so dropping portfolios removes it automatically —
no separate Rails migration is needed for teardown. Delete R2's file
afterward (safe — Rails tracks applied migrations by timestamp in
schema_migrations, not by file presence) and regenerate schema.rb.

IMPORTANT: `op.drop_table` emits a plain `DROP TABLE` (no CASCADE), so
child tables that still reference a parent MUST be dropped first, or
Postgres raises "cannot drop table … because other objects depend on it".
Order below is the dependency-correct leaf-first sequence.

Downgrade is intentionally NOT a full schema restore (same convention as
0015's lossy de-dup, which the audit flagged as acceptable-by-design) —
recreating portfolios + all five satellites requires copy-pasting their
original definitions from migrations 0001, 0008, 0012 and 0013. Left as a
deliberate manual step so a future author re-verifies they actually want
it back before undoing this.
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    # Drop ALL SIX portfolio tables. Dependency-correct leaf-first order:
    #   - portfolio_allocation_history, portfolio_rebalance_trades,
    #     portfolio_drift_alerts all reference portfolios → drop first
    #   - portfolio_holdings, portfolio_recommendations reference portfolios
    #     AND companies (companies must survive) → drop before portfolios
    #   - portfolios dropped last (still owns Rails R2 FK to users)
    op.drop_table("portfolio_allocation_history")
    op.drop_table("portfolio_rebalance_trades")
    op.drop_table("portfolio_drift_alerts")
    op.drop_table("portfolio_holdings")
    op.drop_table("portfolio_recommendations")
    op.drop_table("portfolios")


def downgrade() -> None:
    raise NotImplementedError(
        "Deliberately not reversible — see module docstring. "
        "Recreate all six tables (portfolios, portfolio_holdings, "
        "portfolio_recommendations from 0001; portfolio_allocation_history, "
        "portfolio_rebalance_trades, portfolio_drift_alerts from 0008) if "
        "this table set needs to come back."
    )