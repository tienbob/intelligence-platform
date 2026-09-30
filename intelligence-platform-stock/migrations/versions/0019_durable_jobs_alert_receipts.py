"""Durable work outbox and per-user alert read receipts.

Legacy ownerless alerts have unknown provenance: retain them for admins only.
New scheduler alerts use the false default and remain shared.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('alerts', sa.Column('legacy_private', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute('UPDATE alerts SET legacy_private = true WHERE user_id IS NULL')
    op.create_table('alert_reads',
        sa.Column('alert_id', sa.BigInteger(), sa.ForeignKey('alerts.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), primary_key=True),
    )
    op.create_table('work_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('scope', sa.String(200), nullable=False),
        sa.Column('key', sa.String(200)),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('response', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('scope', 'key', name='uq_work_jobs_scope_key'),
    )
    op.create_index('ix_work_jobs_status', 'work_jobs', ['status'])
    # Upgrade requires stopped old workers (documented deployment procedure).
    op.execute("""UPDATE analyses SET status='failed', llm_analysis=coalesce(llm_analysis, '{}'::jsonb) || '{"_failure_reason":"Interrupted during worker upgrade. Retry as a new analysis."}'::jsonb WHERE status NOT IN ('completed','failed','cancelled')""")

def downgrade():
    op.drop_table('work_jobs')
    op.drop_table('alert_reads')
    op.drop_column('alerts', 'legacy_private')
