"""Allow annual and quarterly statements ending on the same date."""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints('financial_statements'):
        if set(constraint['column_names']) == {'company_id', 'period'}:
            op.drop_constraint(constraint['name'], 'financial_statements', type_='unique')
    for index in inspector.get_indexes('financial_statements'):
        if index.get('unique') and not index.get('duplicates_constraint') and set(index['column_names']) == {'company_id', 'period'}:
            op.drop_index(index['name'], table_name='financial_statements')
    op.create_unique_constraint('uq_financial_statements_company_period_type', 'financial_statements', ['company_id', 'period', 'period_type'])


def downgrade():
    # Refuse a lossy rollback when both period types are present.
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM financial_statements GROUP BY company_id, period HAVING count(*) > 1 LIMIT 1')).first():
        raise RuntimeError('Annual/quarterly pairs exist; reconcile them before downgrade')
    op.drop_constraint('uq_financial_statements_company_period_type', 'financial_statements', type_='unique')
    op.create_unique_constraint('uq_financial_statements_company_period', 'financial_statements', ['company_id', 'period'])
