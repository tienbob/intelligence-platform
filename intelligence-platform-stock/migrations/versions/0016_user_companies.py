"""user_companies junction (User ↔ Company access scoping)

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-27

Application-owned table (docs/TABLE_OWNERSHIP.md): grants a user visibility
of specific tracked companies. Assignment is enforced by the Rails gateway;
the Python service read-scopes company endpoints via ``X-User-Id``.

Backfill: every existing user is granted every currently tracked company,
preserving today's "see everything" behavior at migration time.

NOTE on scale: the backfill below is a single bulk ``CROSS JOIN`` INSERT. It
is correct for small fleet tables (today's case) but blocks the DB on large
user/company bases. For environments with >~5k rows in either table, use the
batched variant documented in MIGRATION_FIX_PLAN.md §P3 instead.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dependency contract: `user_companies` references `users` (Rails-owned)
    # and `companies` (Alembic-owned). Rails must have migrated first. Guard
    # with a clear error instead of Postgres' cryptic "relation does not exist".
    insp = None
    try:
        conn = op.get_bind()
        from sqlalchemy import inspect
        insp = inspect(conn)
    except Exception:
        insp = None
    if insp is not None:
        missing = [t for t in ("users", "companies") if not insp.has_table(t)]
        if missing:
            raise RuntimeError(
                "Cannot create user_companies: missing prerequisite table(s) "
                f"{missing}. The `users` table is created by the Rails "
                "migration pipeline (rails-migrate). Ensure rails-migrate "
                "runs before python-migrate (python-migrate now depends on "
                "rails-migrate in docker-compose)."
            )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_companies (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            company_id BIGINT NOT NULL REFERENCES companies(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_companies_user_company "
        "ON user_companies (user_id, company_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_companies_company_id "
        "ON user_companies (company_id)"
    )

    # Preserve pre-migration visibility: link every existing user to every
    # tracked company. New companies remain unlinked until assigned.
    op.execute(
        """
        INSERT INTO user_companies (user_id, company_id)
        SELECT u.id, c.id FROM users u CROSS JOIN companies c
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_companies")
