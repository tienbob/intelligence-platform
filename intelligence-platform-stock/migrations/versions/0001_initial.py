"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── companies ────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=True),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("cik", sa.String(length=20), nullable=True),
        sa.Column("cusip", sa.String(length=9), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"], unique=True)
    op.create_index("ix_companies_isin", "companies", ["isin"])
    op.create_index("ix_companies_cik", "companies", ["cik"])
    op.create_index("ix_companies_sector", "companies", ["sector"])
    op.create_index("ix_companies_ticker_exchange", "companies", ["ticker", "exchange"])

    # ── stock_prices ─────────────────────────────────────────────
    op.create_table(
        "stock_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adjusted_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_prices_company_id", "stock_prices", ["company_id"])
    op.create_index("ix_stock_prices_timestamp", "stock_prices", ["timestamp"])
    op.create_index("ix_stock_prices_company_timestamp", "stock_prices", ["company_id", "timestamp"])
    op.create_index("ix_stock_prices_company_interval_ts", "stock_prices", ["company_id", "interval", "timestamp"])

    # ── financial_statements ─────────────────────────────────────
    op.create_table(
        "financial_statements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("filing_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("operating_income", sa.Float(), nullable=True),
        sa.Column("net_income", sa.Float(), nullable=True),
        sa.Column("eps", sa.Float(), nullable=True),
        sa.Column("total_assets", sa.Float(), nullable=True),
        sa.Column("total_liabilities", sa.Float(), nullable=True),
        sa.Column("total_debt", sa.Float(), nullable=True),
        sa.Column("cash", sa.Float(), nullable=True),
        sa.Column("shareholders_equity", sa.Float(), nullable=True),
        sa.Column("operating_cash_flow", sa.Float(), nullable=True),
        sa.Column("capital_expenditure", sa.Float(), nullable=True),
        sa.Column("free_cash_flow", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_financial_statements_company_id", "financial_statements", ["company_id"])
    op.create_index("ix_financial_statements_company_period", "financial_statements", ["company_id", "period"])
    op.create_index("ix_financial_statements_source_id", "financial_statements", ["source_id"])

    # ── financial_metrics ────────────────────────────────────────
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pe_ratio", sa.Float(), nullable=True),
        sa.Column("ps_ratio", sa.Float(), nullable=True),
        sa.Column("pb_ratio", sa.Float(), nullable=True),
        sa.Column("ev_ebitda", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("roa", sa.Float(), nullable=True),
        sa.Column("gross_margin", sa.Float(), nullable=True),
        sa.Column("operating_margin", sa.Float(), nullable=True),
        sa.Column("net_margin", sa.Float(), nullable=True),
        sa.Column("debt_equity", sa.Float(), nullable=True),
        sa.Column("current_ratio", sa.Float(), nullable=True),
        sa.Column("fcf_yield", sa.Float(), nullable=True),
        sa.Column("revenue_growth", sa.Float(), nullable=True),
        sa.Column("earnings_growth", sa.Float(), nullable=True),
        sa.Column("fcf_growth", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_financial_metrics_company_id", "financial_metrics", ["company_id"])
    op.create_index("ix_financial_metrics_company_ts", "financial_metrics", ["company_id", "timestamp"])

    # ── news ─────────────────────────────────────────────────────
    op.create_table(
        "news",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("credibility_score", sa.Float(), nullable=True),
        sa.Column("magnitude_score", sa.Float(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_external_id", "news", ["external_id"])
    op.create_index("ix_news_published_at", "news", ["published_at"])
    op.create_index("ix_news_content_hash", "news", ["content_hash"], unique=True)

    # ── company_news ─────────────────────────────────────────────
    op.create_table(
        "company_news",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("news_id", sa.BigInteger(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["news_id"], ["news.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_news_company_id", "company_news", ["company_id"])
    op.create_index("ix_company_news_news_id", "company_news", ["news_id"])
    op.create_index("ix_company_news_company_news", "company_news", ["company_id", "news_id"])

    # ── market_events ────────────────────────────────────────────
    op.create_table(
        "market_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impact", sa.String(length=20), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_news_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["source_news_id"], ["news.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_events_company_id", "market_events", ["company_id"])
    op.create_index("ix_market_events_event_type", "market_events", ["event_type"])
    op.create_index("ix_market_events_event_date", "market_events", ["event_date"])
    op.create_index("ix_market_events_company_date", "market_events", ["company_id", "event_date"])

    # ── event_price_correlations ─────────────────────────────────
    op.create_table(
        "event_price_correlations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("price_before", sa.Float(), nullable=True),
        sa.Column("price_after", sa.Float(), nullable=True),
        sa.Column("price_change", sa.Float(), nullable=True),
        sa.Column("volume_change", sa.Float(), nullable=True),
        sa.Column("volatility_change", sa.Float(), nullable=True),
        sa.Column("time_to_reaction_min", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["market_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_price_correlations_event_id", "event_price_correlations", ["event_id"])
    op.create_index("ix_event_price_correlations_company_id", "event_price_correlations", ["company_id"])

    # ── economic_indicators ──────────────────────────────────────
    op.create_table(
        "economic_indicators",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("indicator", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_economic_indicators_indicator", "economic_indicators", ["indicator"])
    op.create_index("ix_economic_indicators_timestamp", "economic_indicators", ["timestamp"])
    op.create_index("ix_economic_indicators_indicator_ts", "economic_indicators", ["indicator", "timestamp"])

    # ── technical_indicators ─────────────────────────────────────
    op.create_table(
        "technical_indicators",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sma_20", sa.Float(), nullable=True),
        sa.Column("sma_50", sa.Float(), nullable=True),
        sa.Column("sma_200", sa.Float(), nullable=True),
        sa.Column("ema_20", sa.Float(), nullable=True),
        sa.Column("rsi_14", sa.Float(), nullable=True),
        sa.Column("macd", sa.Float(), nullable=True),
        sa.Column("macd_signal", sa.Float(), nullable=True),
        sa.Column("atr", sa.Float(), nullable=True),
        sa.Column("bollinger_upper", sa.Float(), nullable=True),
        sa.Column("bollinger_lower", sa.Float(), nullable=True),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("volatility_30d", sa.Float(), nullable=True),
        sa.Column("momentum", sa.Float(), nullable=True),
        sa.Column("drawdown", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_technical_indicators_company_id", "technical_indicators", ["company_id"])
    op.create_index("ix_technical_indicators_company_ts", "technical_indicators", ["company_id", "timestamp"])

    # ── anomaly_scores ───────────────────────────────────────────
    op.create_table(
        "anomaly_scores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_change_score", sa.Float(), nullable=True),
        sa.Column("volume_score", sa.Float(), nullable=True),
        sa.Column("volatility_score", sa.Float(), nullable=True),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("triggered", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomaly_scores_company_id", "anomaly_scores", ["company_id"])
    op.create_index("ix_anomaly_scores_company_ts", "anomaly_scores", ["company_id", "timestamp"])

    # ── risk_metrics ─────────────────────────────────────────────
    op.create_table(
        "risk_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("volatility", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("value_at_risk", sa.Float(), nullable=True),
        sa.Column("liquidity_score", sa.Float(), nullable=True),
        sa.Column("fundamental_risk", sa.Float(), nullable=True),
        sa.Column("event_risk", sa.Float(), nullable=True),
        sa.Column("concentration_risk", sa.Float(), nullable=True),
        sa.Column("sector_risk", sa.Float(), nullable=True),
        sa.Column("correlation_risk", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_metrics_company_id", "risk_metrics", ["company_id"])
    op.create_index("ix_risk_metrics_company_ts", "risk_metrics", ["company_id", "timestamp"])

    # ── embeddings (pgvector) ────────────────────────────────────
    op.create_table(
        "embeddings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_embeddings_entity_type", "embeddings", ["entity_type"])
    op.create_index("ix_embeddings_entity_id", "embeddings", ["entity_id"])

    # ── analyses ─────────────────────────────────────────────────
    op.create_table(
        "analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_type", sa.String(length=50), nullable=False),
        sa.Column("analysis_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("market_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fundamental_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("technical_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("news_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("macro_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("investment_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("llm_tokens_used", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyses_analysis_id", "analyses", ["analysis_id"], unique=True)
    op.create_index("ix_analyses_company_id", "analyses", ["company_id"])

    # ── investment_scores ────────────────────────────────────────
    op.create_table(
        "investment_scores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fundamental_score", sa.Float(), nullable=True),
        sa.Column("valuation_score", sa.Float(), nullable=True),
        sa.Column("growth_score", sa.Float(), nullable=True),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("catalyst_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investment_scores_company_id", "investment_scores", ["company_id"])
    op.create_index("ix_investment_scores_company_ts", "investment_scores", ["company_id", "timestamp"])

    # ── analysis_sources ─────────────────────────────────────────
    op.create_table(
        "analysis_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("source_name", sa.String(length=100), nullable=True),
        sa.Column("metric", sa.String(length=100), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("period", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_sources_analysis_id", "analysis_sources", ["analysis_id"])

    # ── portfolios ───────────────────────────────────────────────
    op.create_table(
        "portfolios",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("capital", sa.Float(), nullable=False),
        sa.Column("cash_reserve", sa.Float(), nullable=False),
        sa.Column("risk_profile", sa.String(length=20), nullable=False),
        sa.Column("investment_horizon", sa.String(length=20), nullable=False),
        sa.Column("max_position_weight", sa.Float(), nullable=False),
        sa.Column("max_sector_weight", sa.Float(), nullable=False),
        sa.Column("max_portfolio_volatility", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── portfolio_holdings ───────────────────────────────────────
    op.create_table(
        "portfolio_holdings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_holdings_portfolio_id", "portfolio_holdings", ["portfolio_id"])
    op.create_index("ix_portfolio_holdings_company_id", "portfolio_holdings", ["company_id"])
    op.create_index("ix_portfolio_holdings_portfolio_company", "portfolio_holdings", ["portfolio_id", "company_id"])

    # ── portfolio_recommendations ────────────────────────────────
    op.create_table(
        "portfolio_recommendations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.BigInteger(), nullable=False),
        sa.Column("investable_capital", sa.Float(), nullable=False),
        sa.Column("allocation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("portfolio_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_recommendations_portfolio_id", "portfolio_recommendations", ["portfolio_id"])

    # ── raw data tables ──────────────────────────────────────────
    op.create_table(
        "raw_market_data",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_market_data_provider", "raw_market_data", ["provider"])
    op.create_index("ix_raw_market_data_ticker", "raw_market_data", ["ticker"])
    op.create_index("ix_raw_market_data_provider_ticker", "raw_market_data", ["provider", "ticker"])

    op.create_table(
        "raw_sec_filings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("cik", sa.String(length=20), nullable=True),
        sa.Column("ticker", sa.String(length=20), nullable=True),
        sa.Column("filing_type", sa.String(length=20), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_sec_filings_cik", "raw_sec_filings", ["cik"])
    op.create_index("ix_raw_sec_filings_ticker", "raw_sec_filings", ["ticker"])
    op.create_index("ix_raw_sec_filings_filing_type", "raw_sec_filings", ["filing_type"])

    op.create_table(
        "raw_news",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_news_provider", "raw_news", ["provider"])

    op.create_table(
        "raw_macro_data",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("indicator", sa.String(length=100), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_macro_data_indicator", "raw_macro_data", ["indicator"])

    # ── alerts ───────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_company_id", "alerts", ["company_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("raw_macro_data")
    op.drop_table("raw_news")
    op.drop_table("raw_sec_filings")
    op.drop_table("raw_market_data")
    op.drop_table("portfolio_recommendations")
    op.drop_table("portfolio_holdings")
    op.drop_table("portfolios")
    op.drop_table("analysis_sources")
    op.drop_table("investment_scores")
    op.drop_table("analyses")
    op.drop_table("embeddings")
    op.drop_table("risk_metrics")
    op.drop_table("anomaly_scores")
    op.drop_table("technical_indicators")
    op.drop_table("economic_indicators")
    op.drop_table("event_price_correlations")
    op.drop_table("market_events")
    op.drop_table("company_news")
    op.drop_table("news")
    op.drop_table("financial_metrics")
    op.drop_table("financial_statements")
    op.drop_table("stock_prices")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")