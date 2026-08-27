# frozen_string_literal: true

require "jwt"

# Issues and verifies JWT tokens matching the existing FastAPI token shape:
#
#   {
#     "sub":  "42",          # user id (string)
#     "role": "USER",
#     "exp":  <unix ts>,
#     "iat":  <unix ts>,
#     "type": "access" | "refresh"
#   }
#
# HS256, signed with Gateway::JWT_SECRET_KEY.
module JwtService
  module_function

  def issue_access_token(user)
    issue(user, type: "access", expires_in: Gateway::ACCESS_TOKEN_EXPIRES)
  end

  def issue_refresh_token(user)
    issue(user, type: "refresh", expires_in: Gateway::REFRESH_TOKEN_EXPIRES)
  end

  def issue_token_pair(user)
    {
      access_token: issue_access_token(user),
      refresh_token: issue_refresh_token(user),
      token_type: "bearer"
    }
  end

  # Returns the decoded payload (Hash with string keys) or raises.
  def decode(token)
    JWT.decode(token, Gateway::JWT_SECRET_KEY, true, algorithm: Gateway::JWT_ALGORITHM).first
  end

  # Safely decodes and returns payload, or nil if invalid/expired.
  def decode_safe(token)
    decode(token)
  rescue JWT::DecodeError
    nil
  end

  # ── internals ──────────────────────────────────────────────────
  def issue(user, type:, expires_in:)
    now = Time.now.to_i
    payload = {
      "sub" => user.id.to_s,
      "role" => user.role,
      "exp" => now + expires_in.to_i,
      "iat" => now,
      "type" => type
    }
    JWT.encode(payload, Gateway::JWT_SECRET_KEY, Gateway::JWT_ALGORITHM)
  end
  private_class_method :issue
end