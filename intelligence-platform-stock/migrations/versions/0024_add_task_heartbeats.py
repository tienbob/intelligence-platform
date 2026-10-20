"""Add task_heartbeats table for pipeline observability (I2)."""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'task_heartbeats',
        sa.Column('task', sa.String(100), primary_key=True),
        sa.Column('last_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('task_heartbeats')