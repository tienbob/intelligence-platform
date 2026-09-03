"""FIXTURE — deliberately invalid domain migration (Gate 4.3 negative test).

This file is NOT a real migration and must never be loaded by Alembic. It
simulates a domain (Stock) migration that reaches into the framework-owned
``embeddings`` table — exactly the ownership violation the Stage 1 guard
must catch:

    * it is revision 0099 (not in the sanctioned framework-revision allow-list)
    * it alters the framework-owned ``embeddings`` table (adds a domain column)

The guard test asserts this fixture is flagged as a framework-ownership
violation. It lives under tests/fixtures/ so Alembic's version-dir scan
never picks it up.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0099"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # VIOLATION: a domain migration adding a domain-specific column to the
    # framework-owned embeddings table. The Stage 1 guard must reject this.
    op.add_column(
        "embeddings",
        sa.Column("ticker", sa.String(length=16), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_ticker ON embeddings (ticker)"
    )


def downgrade() -> None:
    op.drop_index("ix_embeddings_ticker", table_name="embeddings")
    op.drop_column("embeddings", "ticker")