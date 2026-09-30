"""Backtest snapshot-coverage disclosure (audit F12).

Runs now record exactly which decision inputs were pinned to their snapshot
and which were read live, so a partially pinned run is marked as such instead
of implying full reproducibility.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable (older runs stay null → UI falls back to its default line) and
    # idempotent: shared-DB reruns must not abort on DuplicateColumn.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns("backtest_runs")}
    except Exception:
        cols = None  # table missing — let the DDL raise the real error
    if cols is not None and "snapshot_coverage" not in cols:
        op.add_column(
            "backtest_runs",
            sa.Column("snapshot_coverage", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("backtest_runs", "snapshot_coverage")
