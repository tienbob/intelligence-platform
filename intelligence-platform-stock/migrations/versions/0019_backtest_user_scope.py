"""scope backtest runs and snapshots per owning user

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-28

Product requirement (docs/TABLE_OWNERSHIP.md): a user must only see what
they actually did. Backtest runs and snapshots previously had no owner, so
``list``/``get`` returned the whole table to every caller.

This adds an ownership column:

* ``backtest_runs.user_id`` — a backtest run is a *private* user action. A
  scoped user sees only runs they own.
* ``backtest_snapshots.user_id`` — snapshots are shared reference datasets.
  The scheduler's daily snapshot (``user_id IS NULL``) stays globally visible,
  and any snapshot a user created is private to them. A scoped user sees their
  own plus the global ones, never another user's private snapshots.

Unscoped / system callers (no ``X-User-Id``) continue to see everything.
No backfill is attempted: there is no pre-existing column that could attribute
legacy rows to a user, and any such rows are either scheduler-produced (global,
NULL) or predate scoping. Existing NULL-owner runs are treated as global/system.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", name="fk_backtest_runs_user_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_backtest_runs_user_id", "backtest_runs", ["user_id"]
    )

    op.add_column(
        "backtest_snapshots",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", name="fk_backtest_snapshots_user_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_backtest_snapshots_user_id", "backtest_snapshots", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_snapshots_user_id", table_name="backtest_snapshots")
    op.drop_constraint(
        "fk_backtest_snapshots_user_id", "backtest_snapshots", type_="foreignkey"
    )
    op.drop_column("backtest_snapshots", "user_id")

    op.drop_index("ix_backtest_runs_user_id", table_name="backtest_runs")
    op.drop_constraint(
        "fk_backtest_runs_user_id", "backtest_runs", type_="foreignkey"
    )
    op.drop_column("backtest_runs", "user_id")
