"""Index bounded latest-score and latest-visible-analysis lookups."""
from alembic import op
import sqlalchemy as sa

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    # Avoid blocking analysis writes while upgrading a populated deployment.
    with op.get_context().autocommit_block():
        op.create_index('ix_analyses_completed_latest', 'analyses',
                        ['company_id', sa.text('created_at DESC'), sa.text('id DESC')],
                        postgresql_where=sa.text("status = 'completed'"),
                        postgresql_include=['user_id'], postgresql_concurrently=True)
        op.create_index('ix_investment_scores_latest', 'investment_scores',
                        ['company_id', sa.text('timestamp DESC'), sa.text('id DESC')],
                        postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_investment_scores_latest', table_name='investment_scores', postgresql_concurrently=True)
        op.drop_index('ix_analyses_completed_latest', table_name='analyses', postgresql_concurrently=True)
