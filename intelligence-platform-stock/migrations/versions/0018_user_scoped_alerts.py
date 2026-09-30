"""User-scoped alerts: add nullable user_id + index.

Revision ID: 0018
Revises: 0017

Audit F1/S2: user-created alerts previously had no owner — every
authenticated user could read and dismiss every alert. Now alerts carry
the caller's user_id; system/scheduler alerts stay NULL (shared).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable + no backfill: legacy/system rows stay NULL = shared alerts
    # visible to everyone. New API rows always carry the caller's user_id.
    # No FK to users (Rails-owned table, separate migration history).
    #
    # Idempotent: the Rails mirror migration targets the same shared DB, so
    # either side may have run first. Guard with inspector checks instead of
    # blind add_column/create_index (which aborts on re-run).
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns("alerts")}
    except Exception:
        cols = None  # table missing — let the DDL raise the real error
    if cols is not None and "user_id" not in cols:
        op.add_column("alerts", sa.Column("user_id", sa.BigInteger(), nullable=True))

    insp = sa.inspect(bind)
    try:
        existing = {i["name"] for i in insp.get_indexes("alerts")}
    except Exception:
        existing = None
    if existing is not None and "ix_alerts_user_id" not in existing:
        op.create_index("ix_alerts_user_id", "alerts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_column("alerts", "user_id")
