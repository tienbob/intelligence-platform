"""Phase 6: Add score versioning, data quality, and validation fields to InvestmentScore.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### Phase 6: Score versioning (Section 59) ###
    op.add_column("investment_scores",
        sa.Column("scoring_model", sa.String(50), nullable=True,
                  server_default="investment_score_v1"))
    op.add_column("investment_scores",
        sa.Column("scoring_version", sa.String(20), nullable=True,
                  server_default="1.0"))
    op.add_column("investment_scores",
        sa.Column("scoring_weights", postgresql.JSONB(), nullable=True))

    # ### Phase 6: Data quality (Section 62) ###
    op.add_column("investment_scores",
        sa.Column("data_quality_score", sa.Float(), nullable=True))
    op.add_column("investment_scores",
        sa.Column("validation_issues", postgresql.JSONB(), nullable=True))

    # Set defaults for existing rows
    op.execute(
        sa.text(
            "UPDATE investment_scores SET "
            "scoring_model = 'investment_score_v1', "
            "scoring_version = '1.0' "
            "WHERE scoring_model IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("investment_scores", "validation_issues")
    op.drop_column("investment_scores", "data_quality_score")
    op.drop_column("investment_scores", "scoring_weights")
    op.drop_column("investment_scores", "scoring_version")
    op.drop_column("investment_scores", "scoring_model")
