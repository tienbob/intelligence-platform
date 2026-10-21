# Be sure to restart your server when you modify this file.

# Avoid CORS issues when API is called from the frontend app.
# Handle Cross-Origin Resource Sharing (CORS) in order to accept cross-origin Ajax requests.

# Read more: https://github.com/cyu/rack-cors

# Allowed origins, in priority order:
#   1. CORS_ALLOWED_ORIGINS (comma-separated) — explicit deployments.
#   2. APP_URL — the configured public origin (see app_domain.rb).
#   3. Local development origins (Vite dev server + nginx frontend).
cors_origins = begin
  explicit = ENV["CORS_ALLOWED_ORIGINS"].to_s.split(",").map(&:strip).reject(&:empty?)
  if explicit.empty?
    app_url = ENV["APP_URL"].to_s.strip
    dev = %w[http://localhost:5173 http://localhost:3000 http://127.0.0.1:5173 http://127.0.0.1:3000]
    ([app_url] + dev).reject(&:empty?).uniq
  else
    explicit
  end
end

Rails.application.config.middleware.insert_before 0, Rack::Cors do
  allow do
    # Frontend dev server (Vite) + production nginx origin.
    # Configurable via CORS_ALLOWED_ORIGINS / APP_URL env vars.
    origins(*cors_origins)

    resource "*",
      headers: :any,
      methods: [:get, :post, :put, :patch, :delete, :options, :head],
      expose: ["X-Request-ID"]
  end
end