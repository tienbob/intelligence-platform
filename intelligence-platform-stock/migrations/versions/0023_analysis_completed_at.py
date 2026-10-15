"""Record completion time and index daily deep-dive selection."""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('analyses', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    # Historical exact completion times were not recorded. Last modification
    # is the closest available estimate; future writes use an explicit clock.
    op.execute("UPDATE analyses SET completed_at = updated_at WHERE status = 'completed'")
    with op.get_context().autocommit_block():
        op.create_index('ix_analyses_completed_day', 'analyses',
            ['company_id', sa.text('completed_at DESC'), sa.text('id DESC')],
            postgresql_where=sa.text("status = 'completed'"),
            postgresql_include=['user_id'], postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_analyses_completed_day', table_name='analyses', postgresql_concurrently=True)
    op.drop_column('analyses', 'completed_at')
