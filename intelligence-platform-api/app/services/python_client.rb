# frozen_string_literal: true

require "httpx"

# Internal HTTP client for the Python intelligence service.
#
# Rails is the only client of the Python service. It authenticates via the
# `X-Service-Key` header and forwards the acting user's identity via
# `X-User-Id` / `X-User-Role` so Python can scope requests per user without
# trusting user JWTs.
#
# The Python service wraps responses in a `{"data": ...}` / `{"error": ...}`
# envelope (ResponseEnvelopeMiddleware); this client unwraps `data` so the
# gateway returns the clean payload to the frontend.
class PythonClient
  class PythonError < StandardError
    attr_reader :status, :body

    def initialize(status, body)
      @status = status
      @body = body
      super("Python service error #{status}")
    end
  end

  class << self
    def get(path, query: {}, body: nil, user: nil)
      request(:get, path, query: query, user: user)
    end

    def post(path, body: nil, query: {}, user: nil)
      request(:post, path, body: body, query: query, user: user)
    end

    def put(path, body: nil, query: {}, user: nil)
      request(:put, path, body: body, query: query, user: user)
    end

    def delete(path, body: nil, query: {}, user: nil)
      request(:delete, path, body: body, query: query, user: user)
    end

    # Idempotently ensure a ticker is tracked by the Python service.
    # Returns { "ticker" => ..., "company_id" => ..., "created" => bool } —
    # summons (auto-ingests prices/fundamentals/news) when not yet tracked.
    def ensure_company(ticker, user: nil)
      post("/companies/#{ticker}/ensure", user: user)
    end

    # Raises PythonError (with status + extracted detail) on non-2xx so the
    # controller can propagate the correct upstream status code.
    def request(method, path, body: nil, query: {}, user: nil)
      url = "#{Gateway::PYTHON_INTERNAL_URL}/internal#{path}"
      headers = {
        "Content-Type" => "application/json",
        "X-Service-Key" => Gateway::PYTHON_SERVICE_KEY,
        "X-User-Id" => user&.id.to_s,
        "X-User-Role" => user&.role.to_s
      }

      request_options = {
        headers: headers,
        params: query,
        timeout: { connect_timeout: 5, operation_timeout: 30 }
      }
      request_options[:json] = body if body && !body.empty?

      response = HTTPX.public_send(method, url, **request_options)

      # HTTPX returns an HTTPX::ErrorResponse (no `status` method) on network
      # failures/timeouts. Treat it as a 502 Bad Gateway so the controller
      # returns a graceful error instead of raising NoMethodError (500).
      unless response.respond_to?(:status)
        raise PythonError.new(502, "Python service unavailable (timeout or network error): #{response.error}")
      end

      status = response.status.to_i

      if status >= 400
        detail = extract_error_detail(response.body.to_s)
        raise PythonError.new(status, detail || response.body.to_s)
      end

      parse_body(response.body.to_s)
    end

    def extract_error_detail(raw)
      json = JSON.parse(raw)
      json["detail"] || json.dig("error", "message") if json.is_a?(Hash)
    rescue JSON::ParserError
      nil
    end

    # Unwrap the Python response envelope: {"data": {...}} → {...}
    def parse_body(raw)
      json = JSON.parse(raw)
      return {} if json.nil?

      json.is_a?(Hash) && json.key?("data") ? json["data"] : json
    rescue JSON::ParserError
      raw
    end
  end
end