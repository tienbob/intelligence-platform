"""add instrument_type discriminator to companies

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-08

The platform ingests any ticker (AAPL, NVDA, SPY, …) into ``companies`` with
no discriminator, so an S&P 500 ETF is treated identically to an operating
company. This adds a narrow ``instrument_type`` discriminator
(common_stock / etf / mutual_fund / unknown) so non-stock instruments can be
surfaced in the UI and excluded from company-style analysis.

``server_default`` is set to ``unknown`` only for the DDL so existing rows
backfill safely, then removed so the database can never silently paper over a
classification failure — application code must set the type explicitly.
"""

from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "instrument_type",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_index(
        "ix_companies_instrument_type",
        "companies",
        ["instrument_type"],
    )
    # Drop the server default: new rows must carry an explicit type.
    op.alter_column(
        "companies",
        "instrument_type",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index("ix_companies_instrument_type", table_name="companies")
    op.drop_column("companies", "instrument_type")
