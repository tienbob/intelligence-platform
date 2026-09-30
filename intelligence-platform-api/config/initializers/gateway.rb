# Gateway configuration — JWT auth + Python intelligence service client.
#
# These values are read from the environment to keep secrets out of source code.
# Defaults mirror the Python FastAPI service conventions so the transition is seamless.

module Gateway
  # ── JWT (matches existing FastAPI HS256 token shape) ──────────────
  JWT_SECRET_KEY       = ENV.fetch("JWT_SECRET_KEY", "change-me-in-production-change-me-in-production-1234")
  JWT_ALGORITHM        = ENV.fetch("JWT_ALGORITHM", "HS256")
  ACCESS_TOKEN_EXPIRES = ENV.fetch("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30").to_i.minutes
  REFRESH_TOKEN_EXPIRES = ENV.fetch("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7").to_i.days

  # ── Python intelligence service (internal, service-key protected) ─
  PYTHON_INTERNAL_URL  = ENV.fetch("PYTHON_INTERNAL_URL", "http://localhost:8001")
  PYTHON_SERVICE_KEY   = ENV.fetch("PYTHON_SERVICE_KEY", "dev-service-key-change-me")

  # ── Auth toggle (mirrors Python AUTH_ENABLED) ─────────────────────
  AUTH_ENABLED         = ENV.fetch("AUTH_ENABLED", "false") == "true"

  # ── Fail-closed production guard (audit S1) ───────────────────────
  # Never sign user JWTs with a well-known default secret, and never call the
  # Python service with the dev key, in production. Refuse to boot instead of
  # failing open (mirrors the guard in the Python app/main.py).
  if Rails.env.production?
    _problems = []
    if JWT_SECRET_KEY.strip.empty? || JWT_SECRET_KEY == "change-me-in-production-change-me-in-production-1234"
      _problems << "JWT_SECRET_KEY is the known default"
    end
    if PYTHON_SERVICE_KEY.strip.empty? || PYTHON_SERVICE_KEY == "dev-service-key-change-me"
      _problems << "PYTHON_SERVICE_KEY is the known dev default"
    end
    _problems << "AUTH_ENABLED must be true" unless AUTH_ENABLED
    unless _problems.empty?
      raise "Refusing to boot the gateway in production: #{_problems.join('; ')}. " \
            "Set real secrets (JWT_SECRET_KEY, PYTHON_SERVICE_KEY) or run outside production."
    end
  end
end