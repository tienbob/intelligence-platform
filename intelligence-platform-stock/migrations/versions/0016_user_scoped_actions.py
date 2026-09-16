"""User-scoped actions: analyses + backtest_runs.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable + no backfill: legacy/scheduler rows stay NULL = system rows
    # visible to everyone. New API rows always carry the caller's user_id.
    # No FK to users (Rails-owned table, separate migration history).
    #
    # Idempotent: the Rails mirror migration targets the same shared DB, so
    # either side may have run first. Guard with inspector checks instead of
    # blind add_column/create_index (which aborts with DuplicateColumn /
    # DuplicateTable on re-run).
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in ("analyses", "backtest_runs"):
        try:
            cols = {c["name"] for c in insp.get_columns(table)}
        except Exception:
            continue  # table missing — let the DDL raise the real error
        if "user_id" not in cols:
            op.add_column(table, sa.Column("user_id", sa.BigInteger(), nullable=True))
    insp = sa.inspect(bind)
    for table, ix in (
        ("analyses", "ix_analyses_user_id"),
        ("backtest_runs", "ix_backtest_runs_user_id"),
    ):
        try:
            existing = {i["name"] for i in insp.get_indexes(table)}
        except Exception:
            continue
        if ix not in existing:
            op.create_index(ix, table, ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_user_id", table_name="backtest_runs")
    op.drop_column("backtest_runs", "user_id")
    op.drop_index("ix_analyses_user_id", table_name="analyses")
    op.drop_column("analyses", "user_id")
