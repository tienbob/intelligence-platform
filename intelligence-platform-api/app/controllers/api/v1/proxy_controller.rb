# frozen_string_literal: true

module Api
  module V1
    # Pass-through proxy for Python-owned data endpoints.
    #
    # Rails authenticates + authorizes the request, then forwards to the
    # Python intelligence service's internal API. Python only ever sees the
    # internal service key and the forwarded user identity headers — never the
    # user's JWT.
    class ProxyController < BaseController
      # ── Stocks ──────────────────────────────────────────────
      def stocks_quote
        render_python(:get, "/stocks/#{params[:ticker]}")
      end

      def stocks_prices
        render_python(:get, "/stocks/#{params[:ticker]}/prices", query: request.query_parameters)
      end

      # ── Companies ───────────────────────────────────────────
      def companies
        render_python(:get, "/companies/", query: request.query_parameters)
      end

      def company
        render_python(:get, "/companies/#{params[:ticker]}")
      end

      # ── Prices ──────────────────────────────────────────────
      def prices
        render_python(:get, "/prices/#{params[:ticker]}", query: request.query_parameters)
      end

      # ── Financials ──────────────────────────────────────────
      def financial_statements
        render_python(:get, "/financials/#{params[:ticker]}/statements", query: request.query_parameters)
      end

      def financial_metrics
        render_python(:get, "/financials/#{params[:ticker]}/metrics")
      end

      def financial_technical
        render_python(:get, "/financials/#{params[:ticker]}/technical")
      end

      # ── News ────────────────────────────────────────────────
      def news
        render_python(:get, "/news/", query: request.query_parameters)
      end

      def news_item
        render_python(:get, "/news/#{params[:id]}")
      end

      # ── Events ──────────────────────────────────────────────
      def events
        render_python(:get, "/events/", query: request.query_parameters)
      end

      def event
        render_python(:get, "/events/#{params[:id]}")
      end

      # ── Market ──────────────────────────────────────────────
      def market_overview
        render_python(:get, "/market/overview")
      end

      def market_indices
        render_python(:get, "/market/indices")
      end

      def market_top_movers
        render_python(:get, "/market/top-movers")
      end

      # ── Portfolio optimizer (stateless — proxied to Python) ─
      def optimize
        render_python(:post, "/portfolio/optimize", body: parsed_body, query: {})
      end

      # ── Analysis ────────────────────────────────────────────
      def analysis_company
        render_python(:post, "/analysis/company", body: parsed_body, query: {})
      end

      def analysis
        render_python(:get, "/analysis/#{params[:id]}")
      end

      def analysis_delete
        render_python(:delete, "/analysis/#{params[:id]}")
      end

      def analysis_jobs
        render_python(:get, "/analysis/jobs", query: request.query_parameters)
      end

      # ── Investments ─────────────────────────────────────────
      def opportunities
        render_python(:get, "/investments/opportunities", query: request.query_parameters)
      end

      # ── Alerts ──────────────────────────────────────────────
      def alerts
        render_python(:get, "/alerts/", query: request.query_parameters)
      end

      def alert_create
        render_python(:post, "/alerts/", body: parsed_body, query: {})
      end

      def alert
        render_python(:get, "/alerts/#{params[:id]}")
      end

      def alert_read
        render_python(:post, "/alerts/#{params[:id]}/read", body: {})
      end

      # ── Backtest ────────────────────────────────────────────
      def backtest_runs
        render_python(:get, "/backtest/runs", query: request.query_parameters)
      end

      def backtest_run
        render_python(:get, "/backtest/runs/#{params[:id]}")
      end

      def backtest_trades
        render_python(:get, "/backtest/runs/#{params[:id]}/trades", query: request.query_parameters)
      end

      def backtest_create
        render_python(:post, "/backtest/runs", body: parsed_body)
      end

      def backtest_snapshots
        render_python(:get, "/backtest/snapshots", query: request.query_parameters)
      end

      def backtest_snapshot_create
        render_python(:post, "/backtest/snapshots", body: parsed_body)
      end

      private

      def render_python(method, path, query: {}, body: nil)
        data = PythonClient.public_send(method, path, query: query, body: body, user: current_user)
        render json: data, status: :ok
      rescue PythonClient::PythonError => e
        # Propagate the upstream status code (e.g. 404 → 404) and detail.
        render json: { detail: e.body }, status: e.status
      end

      # Parse the request body as JSON (for POST/PUT pass-through).
      def parsed_body
        raw = request.raw_post
        return {} if raw.blank?

        JSON.parse(raw)
      rescue JSON::ParserError
        {}
      end
    end
  end
end