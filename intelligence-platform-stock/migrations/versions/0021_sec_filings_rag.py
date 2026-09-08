"""add sec_filings table for SEC filing RAG retrieval (Gate 6, analysis integrity)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-04

The framework analysis must be able to audit financial claims (revenue, net
income, cash flow, debt, guidance, risk disclosures) against the primary
source. This migration adds the canonical ``sec_filings`` table that stores
human-readable text chunks derived from SEC EDGAR XBRL facts. These chunks are
embedded and retrieved by the RAG service (``entity_type = 'sec_filing'``).

One row per (company_id, fiscal_year, period, form).
"""

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_filings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("cik", sa.String(length=20), nullable=True),
        sa.Column("filing_type", sa.String(length=20), nullable=True),
        sa.Column("fiscal_year", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=10), nullable=True),
        sa.Column("form", sa.String(length=20), nullable=True),
        sa.Column("filed_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source", sa.String(length=50), nullable=False, server_default="SEC"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sec_filings_company_id", "sec_filings", ["company_id"]
    )
    op.create_index("ix_sec_filings_cik", "sec_filings", ["cik"])
    op.create_index(
        "ix_sec_filings_company_period",
        "sec_filings",
        ["company_id", "fiscal_year", "period", "form"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sec_filings_company_period", table_name="sec_filings"
    )
    op.drop_index("ix_sec_filings_cik", table_name="sec_filings")
    op.drop_index("ix_sec_filings_company_id", table_name="sec_filings")
    op.drop_table("sec_filings")