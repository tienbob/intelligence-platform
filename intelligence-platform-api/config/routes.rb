Rails.application.routes.draw do
  # Define your application routes per the DSL in https://guides.rubyonrails.org/routing.html

  # Rails health check (used by load balancers / uptime monitors)
  get "up" => "rails/health#show", as: :rails_health_check

  # Public health/metrics — proxied to the Python service
  # Devise routes (added by generator) — we use custom /auth/* endpoints instead.
  # devise_for :users

  get "health/live",  to: "public#health_live"
  get "health/ready", to: "public#health_ready"
  get "health",       to: "public#health"
  get "metrics",      to: "public#metrics"

  # ── API v1 ─────────────────────────────────────────────────────
  namespace :api do
    namespace :v1 do
      # Auth (Rails-owned)
      post "auth/register", to: "auth#register"
      post "auth/login",    to: "auth#login"
      post "auth/refresh",  to: "auth#refresh"
      get  "auth/me",       to: "auth#me"

      # ── Portfolio optimizer (stateless, proxied to Python) ──
      post "portfolio/optimize", to: "proxy#optimize"

      # ── Python-backed pass-through (proxied to internal API) ──
      get "stocks/:ticker",                 to: "proxy#stocks_quote"
      get "stocks/:ticker/prices",          to: "proxy#stocks_prices"
      get "companies",                      to: "proxy#companies"
      get "companies/:ticker",              to: "proxy#company"
      get "prices/:ticker",                 to: "proxy#prices"
      get "financials/:ticker/statements",  to: "proxy#financial_statements"
      get "financials/:ticker/metrics",     to: "proxy#financial_metrics"
      get "financials/:ticker/technical",   to: "proxy#financial_technical"
      get "news",                           to: "proxy#news"
      get "news/:id",                       to: "proxy#news_item"
      get "events",                         to: "proxy#events"
      get "events/:id",                     to: "proxy#event"
      get "market/overview",                to: "proxy#market_overview"
      get "market/indices",                 to: "proxy#market_indices"
      get "market/top-movers",              to: "proxy#market_top_movers"
      post "analysis/company",              to: "proxy#analysis_company"
      get "analysis/:id",                   to: "proxy#analysis"
      delete "analysis/:id",                to: "proxy#analysis_delete"
      get "analysis/jobs",                  to: "proxy#analysis_jobs"
      get "investments/opportunities",      to: "proxy#opportunities"
      get "alerts",                         to: "proxy#alerts"
      post "alerts",                        to: "proxy#alert_create"
      get "alerts/:id",                     to: "proxy#alert"
      post "alerts/:id/read",               to: "proxy#alert_read"
      get "backtest/runs",                  to: "proxy#backtest_runs"
      get "backtest/runs/:id",              to: "proxy#backtest_run"
      get "backtest/runs/:id/trades",       to: "proxy#backtest_trades"
      post "backtest/runs",                 to: "proxy#backtest_create"
      get "backtest/snapshots",             to: "proxy#backtest_snapshots"
      post "backtest/snapshots",            to: "proxy#backtest_snapshot_create"
    end
  end
end
