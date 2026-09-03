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
      # Ticker-scoped reads that must resolve (or summon) the company first.
      TICKER_SCOPED_ACTIONS = %w[
        stocks_quote stocks_prices company prices
        financial_statements financial_metrics financial_technical
      ].freeze

      # Access-grant orchestration (docs/TABLE_OWNERSHIP.md): Rails owns
      # `user_companies` assignment. For logged-in users, ensure the ticker
      # is tracked (Python summons/ingests it when missing) and the user is
      # granted visibility BEFORE the read is proxied; Python scopes every
      # read to granted companies. Anonymous requests skip this — Python
      # self-populates on unscoped reads.
      before_action :ensure_company_access!, only: TICKER_SCOPED_ACTIONS

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

      # ── Company summon + grant (see before_action above) ──────────
      def ensure_company_access!
        return if current_user.id.blank?

        symbol = params[:ticker].to_s.strip.upcase
        return if symbol.blank?

        Rails.cache.fetch("company-grant/#{current_user.id}/#{symbol}", expires_in: 5.minutes) do
          result = PythonClient.ensure_company(symbol, user: current_user)
          company_id = result["company_id"]
          raise PythonClient::PythonError.new(404, "ensure_company returned no company_id for #{symbol}") if company_id.blank?

          begin
            UserCompany.find_or_create_by!(user_id: current_user.id, company_id: company_id)
          rescue ActiveRecord::RecordNotUnique
            nil # concurrent duplicate grant — the UNIQUE index guarantees one row
          end
          true
        end
      rescue PythonClient::PythonError => e
        # Non-blocking: the proxied call below returns the proper upstream
        # status (404 for an unknown/ingest-failed ticker, 502 if Python is
        # down). Grant failures must not mask the real read result.
        Rails.logger.warn("[proxy] ensure_company failed: #{e.status} #{e.body}")
        nil
      end

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