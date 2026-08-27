# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.0].define(version: 2026_08_10_025318) do
  # These are extensions that must be enabled in order to support this database
  enable_extension "pg_catalog.plpgsql"
  enable_extension "vector"

  create_table "alembic_version", primary_key: "version_num", id: { type: :string, limit: 32 }, force: :cascade do |t|
  end

  create_table "alerts", force: :cascade do |t|
    t.bigint "company_id"
    t.string "alert_type", limit: 50, null: false
    t.string "severity", limit: 20, null: false
    t.text "message", null: false
    t.jsonb "data"
    t.boolean "is_read", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["alert_type"], name: "ix_alerts_alert_type"
    t.index ["company_id"], name: "ix_alerts_company_id"
  end

  create_table "analyses", force: :cascade do |t|
    t.string "analysis_id", limit: 36, null: false
    t.bigint "company_id", null: false
    t.string "analysis_type", limit: 50, null: false
    t.string "analysis_version", limit: 20, null: false
    t.string "status", limit: 20, null: false
    t.jsonb "market_snapshot"
    t.jsonb "fundamental_snapshot"
    t.jsonb "technical_snapshot"
    t.jsonb "news_snapshot"
    t.jsonb "macro_snapshot"
    t.jsonb "risk_snapshot"
    t.jsonb "llm_analysis"
    t.float "investment_score"
    t.float "risk_score"
    t.float "confidence_score"
    t.string "prompt_version", limit: 20
    t.string "llm_model", limit: 100
    t.integer "llm_tokens_used"
    t.float "duration_seconds"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["analysis_id"], name: "ix_analyses_analysis_id", unique: true
    t.index ["company_id"], name: "ix_analyses_company_id"
  end

  create_table "analysis_sources", force: :cascade do |t|
    t.bigint "analysis_id", null: false
    t.text "claim", null: false
    t.string "source_type", limit: 50
    t.string "source_name", limit: 100
    t.string "metric", limit: 100
    t.float "value"
    t.string "period", limit: 20
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["analysis_id"], name: "ix_analysis_sources_analysis_id"
  end

  create_table "anomaly_scores", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.float "price_change_score"
    t.float "volume_score"
    t.float "volatility_score"
    t.float "technical_score"
    t.float "overall_score"
    t.boolean "triggered", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "timestamp"], name: "ix_anomaly_scores_company_ts"
    t.index ["company_id"], name: "ix_anomaly_scores_company_id"
  end

  create_table "backtest_ai_evaluations", force: :cascade do |t|
    t.bigint "run_id", null: false
    t.bigint "analysis_id"
    t.string "ticker", limit: 20, null: false
    t.timestamptz "analysis_date", null: false
    t.float "llm_confidence"
    t.string "llm_direction", limit: 20
    t.string "actual_direction", limit: 20
    t.boolean "direction_accuracy"
    t.float "forward_return"
    t.bigint "evidence_count"
    t.boolean "source_backed"
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["run_id"], name: "ix_backtest_ai_evaluations_run_id"
  end

  create_table "backtest_benchmarks", force: :cascade do |t|
    t.bigint "run_id", null: false
    t.string "benchmark_ticker", limit: 20, null: false
    t.float "benchmark_return"
    t.float "strategy_return"
    t.float "alpha"
    t.float "beta"
    t.float "tracking_error"
    t.float "information_ratio"
    t.boolean "outperformed"
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["run_id"], name: "ix_backtest_benchmarks_run_id"
  end

  create_table "backtest_results", force: :cascade do |t|
    t.bigint "run_id", null: false
    t.float "total_return"
    t.float "annualized_return"
    t.float "volatility"
    t.float "sharpe_ratio"
    t.float "max_drawdown"
    t.float "win_rate"
    t.bigint "total_trades"
    t.float "final_capital"
    t.jsonb "equity_curve"
    t.bigint "trade_count"
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["run_id"], name: "ix_backtest_results_run_id"
  end

  create_table "backtest_runs", force: :cascade do |t|
    t.string "name", limit: 200, null: false
    t.string "strategy", limit: 50, null: false
    t.string "status", limit: 20, default: "queued", null: false
    t.timestamptz "start_date", null: false
    t.timestamptz "end_date", null: false
    t.float "initial_capital", default: 100000.0, null: false
    t.string "benchmark_ticker", limit: 20, default: "SPY"
    t.jsonb "parameters"
    t.bigint "snapshot_id"
    t.string "scoring_model", limit: 50
    t.string "scoring_version", limit: 20
    t.string "prompt_version", limit: 20
    t.string "data_version", limit: 50
    t.text "error_message"
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["strategy"], name: "ix_backtest_runs_strategy"
  end

  create_table "backtest_score_evaluations", force: :cascade do |t|
    t.bigint "run_id", null: false
    t.string "ticker", limit: 20, null: false
    t.timestamptz "score_date", null: false
    t.float "score", null: false
    t.string "recommendation", limit: 20
    t.float "forward_return_1m"
    t.float "forward_return_3m"
    t.float "forward_return_6m"
    t.string "actual_outcome", limit: 20
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["run_id", "ticker"], name: "ix_backtest_score_eval_run_ticker"
    t.index ["run_id"], name: "ix_backtest_score_evaluations_run_id"
  end

  create_table "backtest_snapshots", force: :cascade do |t|
    t.string "name", limit: 200, null: false
    t.timestamptz "as_of", null: false
    t.text "description"
    t.jsonb "prices"
    t.jsonb "scores"
    t.jsonb "fundamentals"
    t.jsonb "events"
    t.jsonb "news"
    t.string "source_data_version", limit: 50
    t.string "created_by", limit: 100
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["as_of"], name: "ix_backtest_snapshots_as_of"
  end

  create_table "backtest_trades", force: :cascade do |t|
    t.bigint "run_id", null: false
    t.string "ticker", limit: 20, null: false
    t.string "action", limit: 10, null: false
    t.timestamptz "trade_date", null: false
    t.float "price", null: false
    t.float "shares", null: false
    t.float "amount", null: false
    t.string "reason", limit: 200
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["run_id", "trade_date"], name: "ix_backtest_trades_run_date"
    t.index ["run_id"], name: "ix_backtest_trades_run_id"
  end

  create_table "companies", force: :cascade do |t|
    t.string "ticker", limit: 20, null: false
    t.string "name", limit: 255, null: false
    t.string "exchange", limit: 50
    t.string "isin", limit: 12
    t.string "cik", limit: 20
    t.string "cusip", limit: 9
    t.string "country", limit: 100
    t.string "sector", limit: 100
    t.string "industry", limit: 255
    t.float "market_cap"
    t.text "description"
    t.string "website", limit: 500
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["cik"], name: "ix_companies_cik"
    t.index ["isin"], name: "ix_companies_isin"
    t.index ["sector"], name: "ix_companies_sector"
    t.index ["ticker", "exchange"], name: "ix_companies_ticker_exchange"
    t.index ["ticker"], name: "ix_companies_ticker", unique: true
  end

  create_table "company_news", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.bigint "news_id", null: false
    t.float "relevance_score"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.string "extraction_method", limit: 50
    t.float "confidence"
    t.index ["company_id", "news_id"], name: "ix_company_news_company_news"
    t.index ["company_id"], name: "ix_company_news_company_id"
    t.index ["news_id"], name: "ix_company_news_news_id"
    t.unique_constraint ["company_id", "news_id"], name: "uq_company_news_company_news"
  end

  create_table "economic_indicators", force: :cascade do |t|
    t.string "indicator", limit: 100, null: false
    t.timestamptz "timestamp", null: false
    t.float "value", null: false
    t.string "unit", limit: 50
    t.string "source", limit: 50, null: false
    t.string "frequency", limit: 20
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["indicator", "timestamp"], name: "ix_economic_indicators_indicator_ts"
    t.index ["indicator"], name: "ix_economic_indicators_indicator"
    t.index ["timestamp"], name: "ix_economic_indicators_timestamp"
    t.unique_constraint ["indicator", "timestamp"], name: "uq_economic_indicators_indicator_timestamp"
  end

# Could not dump table "embeddings" because of following StandardError
#   Unknown type 'vector(3072)' for column 'embedding'


  create_table "event_price_correlations", force: :cascade do |t|
    t.bigint "event_id", null: false
    t.bigint "company_id", null: false
    t.float "price_before"
    t.float "price_after"
    t.float "price_change"
    t.float "volume_change"
    t.float "volatility_change"
    t.bigint "time_to_reaction_min"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id"], name: "ix_event_price_correlations_company_id"
    t.index ["event_id"], name: "ix_event_price_correlations_event_id"
  end

  create_table "financial_metrics", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.float "pe_ratio"
    t.float "ps_ratio"
    t.float "pb_ratio"
    t.float "ev_ebitda"
    t.float "roe"
    t.float "roa"
    t.float "gross_margin"
    t.float "operating_margin"
    t.float "net_margin"
    t.float "debt_equity"
    t.float "current_ratio"
    t.float "fcf_yield"
    t.float "revenue_growth"
    t.float "earnings_growth"
    t.float "fcf_growth"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "timestamp"], name: "ix_financial_metrics_company_ts"
    t.index ["company_id"], name: "ix_financial_metrics_company_id"
  end

  create_table "financial_statements", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.string "period", limit: 20, null: false
    t.string "period_type", limit: 20, null: false
    t.string "currency", limit: 10, null: false
    t.timestamptz "filing_date"
    t.float "revenue"
    t.float "gross_profit"
    t.float "operating_income"
    t.float "net_income"
    t.float "eps"
    t.float "total_assets"
    t.float "total_liabilities"
    t.float "total_debt"
    t.float "cash"
    t.float "shareholders_equity"
    t.float "operating_cash_flow"
    t.float "capital_expenditure"
    t.float "free_cash_flow"
    t.string "source"
    t.string "source_id"
    t.timestamptz "retrieved_at"
    t.timestamptz "published_at"
    t.string "data_version"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "period"], name: "ix_financial_statements_company_period"
    t.index ["company_id"], name: "ix_financial_statements_company_id"
    t.index ["source_id"], name: "ix_financial_statements_source_id"
    t.unique_constraint ["company_id", "period"], name: "uq_financial_statements_company_period"
  end

  create_table "investment_scores", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.float "fundamental_score"
    t.float "valuation_score"
    t.float "growth_score"
    t.float "technical_score"
    t.float "sentiment_score"
    t.float "catalyst_score"
    t.float "risk_score"
    t.float "overall_score"
    t.float "confidence"
    t.string "recommendation", limit: 20
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.string "scoring_model", limit: 50, default: "investment_score_v1"
    t.string "scoring_version", limit: 20, default: "1.0"
    t.jsonb "scoring_weights"
    t.float "data_quality_score"
    t.jsonb "validation_issues"
    t.index ["company_id", "timestamp"], name: "ix_investment_scores_company_ts"
    t.index ["company_id"], name: "ix_investment_scores_company_id"
  end

  create_table "market_events", force: :cascade do |t|
    t.bigint "company_id"
    t.string "event_type", limit: 50, null: false
    t.timestamptz "event_date", null: false
    t.string "impact", limit: 20
    t.float "impact_score"
    t.float "confidence"
    t.text "description"
    t.bigint "source_news_id"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.float "materiality_score"
    t.float "effective_weight"
    t.index ["company_id", "event_date"], name: "ix_market_events_company_date"
    t.index ["company_id"], name: "ix_market_events_company_id"
    t.index ["event_date"], name: "ix_market_events_event_date"
    t.index ["event_type"], name: "ix_market_events_event_type"
    t.unique_constraint ["company_id", "source_news_id", "event_type"], name: "uq_market_events_company_news_type"
  end

  create_table "news", force: :cascade do |t|
    t.string "external_id", limit: 255
    t.string "source", limit: 100, null: false
    t.string "title", limit: 500, null: false
    t.string "url", limit: 1000
    t.timestamptz "published_at", null: false
    t.text "content"
    t.text "summary"
    t.string "language", limit: 10, null: false
    t.string "content_hash", limit: 64
    t.float "sentiment"
    t.float "relevance_score"
    t.float "credibility_score"
    t.float "magnitude_score"
    t.float "impact_score"
    t.float "confidence_score"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.float "materiality_score"
    t.float "effective_weight"
    t.index ["content_hash"], name: "ix_news_content_hash", unique: true
    t.index ["external_id"], name: "ix_news_external_id"
    t.index ["published_at"], name: "ix_news_published_at"
    t.index ["source", "external_id"], name: "uq_news_source_external_id", unique: true, where: "(external_id IS NOT NULL AND external_id <> '')"
  end

  create_table "portfolio_allocation_history", force: :cascade do |t|
    t.bigint "portfolio_id", null: false
    t.bigint "recommendation_id"
    t.jsonb "allocation"
    t.jsonb "portfolio_metrics"
    t.float "cash_reserve"
    t.float "investable_capital"
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["portfolio_id"], name: "ix_portfolio_allocation_history_portfolio_id"
  end

  create_table "portfolio_drift_alerts", force: :cascade do |t|
    t.bigint "portfolio_id", null: false
    t.string "ticker", limit: 20
    t.string "drift_type", limit: 50, null: false
    t.float "current_value", null: false
    t.float "target_value", null: false
    t.float "threshold", null: false
    t.string "severity", limit: 20, default: "medium", null: false
    t.text "message", null: false
    t.boolean "is_resolved", default: false, null: false
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["portfolio_id"], name: "ix_portfolio_drift_alerts_portfolio_id"
  end

  create_table "portfolio_holdings", force: :cascade do |t|
    t.bigint "portfolio_id", null: false
    t.bigint "company_id", null: false
    t.float "weight", null: false
    t.float "amount", null: false
    t.float "shares"
    t.float "entry_price"
    t.float "current_price"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id"], name: "ix_portfolio_holdings_company_id"
    t.index ["portfolio_id", "company_id"], name: "ix_portfolio_holdings_portfolio_company"
    t.index ["portfolio_id"], name: "ix_portfolio_holdings_portfolio_id"
  end

  create_table "portfolio_rebalance_trades", force: :cascade do |t|
    t.bigint "portfolio_id", null: false
    t.string "ticker", limit: 20, null: false
    t.string "action", limit: 10, null: false
    t.float "target_weight", null: false
    t.float "current_weight", null: false
    t.float "weight_delta", null: false
    t.float "amount", null: false
    t.float "shares"
    t.float "price"
    t.string "status", limit: 20, default: "PENDING", null: false
    t.string "reason", limit: 200
    t.timestamptz "created_at"
    t.timestamptz "updated_at"
    t.index ["portfolio_id"], name: "ix_portfolio_rebalance_trades_portfolio_id"
  end

  create_table "portfolio_recommendations", force: :cascade do |t|
    t.bigint "portfolio_id", null: false
    t.float "investable_capital", null: false
    t.jsonb "allocation"
    t.jsonb "portfolio_metrics"
    t.text "explanation"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["portfolio_id"], name: "ix_portfolio_recommendations_portfolio_id"
  end

  create_table "portfolios", force: :cascade do |t|
    t.string "name", limit: 100, null: false
    t.float "capital", null: false
    t.float "cash_reserve", null: false
    t.string "risk_profile", limit: 20, null: false
    t.string "investment_horizon", limit: 20, null: false
    t.float "max_position_weight", null: false
    t.float "max_sector_weight", null: false
    t.float "max_portfolio_volatility", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.bigint "user_id", null: false
    t.float "cash_balance", default: 0.0, null: false
    t.integer "version", default: 1, null: false
    t.index ["user_id"], name: "index_portfolios_on_user_id"
  end

  create_table "raw_macro_data", force: :cascade do |t|
    t.string "provider", limit: 50, null: false
    t.string "endpoint", limit: 255, null: false
    t.string "indicator", limit: 100
    t.timestamptz "retrieved_at", null: false
    t.jsonb "payload", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["indicator"], name: "ix_raw_macro_data_indicator"
  end

  create_table "raw_market_data", force: :cascade do |t|
    t.string "provider", limit: 50, null: false
    t.string "endpoint", limit: 255, null: false
    t.string "ticker", limit: 20
    t.timestamptz "retrieved_at", null: false
    t.jsonb "payload", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["provider", "ticker"], name: "ix_raw_market_data_provider_ticker"
    t.index ["provider"], name: "ix_raw_market_data_provider"
    t.index ["ticker"], name: "ix_raw_market_data_ticker"
  end

  create_table "raw_news", force: :cascade do |t|
    t.string "provider", limit: 50, null: false
    t.string "endpoint", limit: 255, null: false
    t.timestamptz "retrieved_at", null: false
    t.jsonb "payload", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["provider"], name: "ix_raw_news_provider"
  end

  create_table "raw_sec_filings", force: :cascade do |t|
    t.string "provider", limit: 50, null: false
    t.string "endpoint", limit: 255, null: false
    t.string "cik", limit: 20
    t.string "ticker", limit: 20
    t.string "filing_type", limit: 20
    t.timestamptz "retrieved_at", null: false
    t.jsonb "payload", null: false
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["cik"], name: "ix_raw_sec_filings_cik"
    t.index ["filing_type"], name: "ix_raw_sec_filings_filing_type"
    t.index ["ticker"], name: "ix_raw_sec_filings_ticker"
  end

  create_table "risk_metrics", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.float "risk_score"
    t.float "volatility"
    t.float "beta"
    t.float "max_drawdown"
    t.float "value_at_risk"
    t.float "liquidity_score"
    t.float "fundamental_risk"
    t.float "event_risk"
    t.float "concentration_risk"
    t.float "sector_risk"
    t.float "correlation_risk"
    t.float "confidence"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "timestamp"], name: "ix_risk_metrics_company_ts"
    t.index ["company_id"], name: "ix_risk_metrics_company_id"
  end

  create_table "stock_prices", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.string "interval", limit: 10, default: "1d", null: false
    t.float "open", null: false
    t.float "high", null: false
    t.float "low", null: false
    t.float "close", null: false
    t.float "adjusted_close"
    t.bigint "volume", null: false
    t.string "source", limit: 50, null: false
    t.string "provider_record_id", limit: 255
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "interval", "timestamp"], name: "ix_stock_prices_company_interval_ts"
    t.index ["company_id", "timestamp"], name: "ix_stock_prices_company_timestamp"
    t.index ["company_id"], name: "ix_stock_prices_company_id"
    t.index ["timestamp"], name: "ix_stock_prices_timestamp"
    t.unique_constraint ["company_id", "interval", "timestamp"], name: "uq_stock_prices_company_interval_timestamp"
  end

  create_table "technical_indicators", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.timestamptz "timestamp", null: false
    t.float "sma_20"
    t.float "sma_50"
    t.float "sma_200"
    t.float "ema_20"
    t.float "rsi_14"
    t.float "macd"
    t.float "macd_signal"
    t.float "atr"
    t.float "bollinger_upper"
    t.float "bollinger_lower"
    t.float "vwap"
    t.float "volatility_30d"
    t.float "momentum"
    t.float "drawdown"
    t.timestamptz "created_at", default: -> { "now()" }, null: false
    t.timestamptz "updated_at", default: -> { "now()" }, null: false
    t.index ["company_id", "timestamp"], name: "ix_technical_indicators_company_ts"
    t.index ["company_id"], name: "ix_technical_indicators_company_id"
  end

  create_table "users", force: :cascade do |t|
    t.string "email", limit: 255, null: false
    t.string "encrypted_password", limit: 255, null: false
    t.string "name", limit: 100, null: false
    t.string "role", limit: 20, default: "USER", null: false
    t.boolean "is_active", default: true, null: false
    t.datetime "created_at", null: false
    t.datetime "updated_at", null: false
    t.string "reset_password_token"
    t.datetime "reset_password_sent_at"
    t.datetime "remember_created_at"
    t.index ["email"], name: "index_users_on_email", unique: true
    t.index ["reset_password_token"], name: "index_users_on_reset_password_token", unique: true
  end

  add_foreign_key "alerts", "companies", name: "alerts_company_id_fkey"
  add_foreign_key "analyses", "companies", name: "analyses_company_id_fkey"
  add_foreign_key "analysis_sources", "analyses", name: "analysis_sources_analysis_id_fkey"
  add_foreign_key "anomaly_scores", "companies", name: "anomaly_scores_company_id_fkey"
  add_foreign_key "backtest_ai_evaluations", "analyses", name: "backtest_ai_evaluations_analysis_id_fkey"
  add_foreign_key "backtest_ai_evaluations", "backtest_runs", column: "run_id", name: "backtest_ai_evaluations_run_id_fkey"
  add_foreign_key "backtest_benchmarks", "backtest_runs", column: "run_id", name: "backtest_benchmarks_run_id_fkey"
  add_foreign_key "backtest_results", "backtest_runs", column: "run_id", name: "backtest_results_run_id_fkey"
  add_foreign_key "backtest_runs", "backtest_snapshots", column: "snapshot_id", name: "backtest_runs_snapshot_id_fkey"
  add_foreign_key "backtest_score_evaluations", "backtest_runs", column: "run_id", name: "backtest_score_evaluations_run_id_fkey"
  add_foreign_key "backtest_trades", "backtest_runs", column: "run_id", name: "backtest_trades_run_id_fkey"
  add_foreign_key "company_news", "companies", name: "company_news_company_id_fkey"
  add_foreign_key "company_news", "news", name: "company_news_news_id_fkey"
  add_foreign_key "event_price_correlations", "companies", name: "event_price_correlations_company_id_fkey"
  add_foreign_key "event_price_correlations", "market_events", column: "event_id", name: "event_price_correlations_event_id_fkey"
  add_foreign_key "financial_metrics", "companies", name: "financial_metrics_company_id_fkey"
  add_foreign_key "financial_statements", "companies", name: "financial_statements_company_id_fkey"
  add_foreign_key "investment_scores", "companies", name: "investment_scores_company_id_fkey"
  add_foreign_key "market_events", "companies", name: "market_events_company_id_fkey"
  add_foreign_key "market_events", "news", column: "source_news_id", name: "market_events_source_news_id_fkey"
  add_foreign_key "portfolio_allocation_history", "portfolio_recommendations", column: "recommendation_id", name: "portfolio_allocation_history_recommendation_id_fkey"
  add_foreign_key "portfolio_allocation_history", "portfolios", name: "portfolio_allocation_history_portfolio_id_fkey"
  add_foreign_key "portfolio_drift_alerts", "portfolios", name: "portfolio_drift_alerts_portfolio_id_fkey"
  add_foreign_key "portfolio_holdings", "companies", name: "portfolio_holdings_company_id_fkey"
  add_foreign_key "portfolio_holdings", "portfolios", name: "portfolio_holdings_portfolio_id_fkey"
  add_foreign_key "portfolio_rebalance_trades", "portfolios", name: "portfolio_rebalance_trades_portfolio_id_fkey"
  add_foreign_key "portfolio_recommendations", "portfolios", name: "portfolio_recommendations_portfolio_id_fkey"
  add_foreign_key "portfolios", "users"
  add_foreign_key "risk_metrics", "companies", name: "risk_metrics_company_id_fkey"
  add_foreign_key "stock_prices", "companies", name: "stock_prices_company_id_fkey"
  add_foreign_key "technical_indicators", "companies", name: "technical_indicators_company_id_fkey"
end
