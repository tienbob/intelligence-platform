# frozen_string_literal: true

require "jwt"
require "digest"
require "securerandom"
require "active_support/security_utils"

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

  def issue_token_pair(user, session: nil)
    nonce = SecureRandom.hex(32)
    session ||= AuthSession.new(id: SecureRandom.uuid, user_id: user.id)
    session.refresh_digest = Digest::SHA256.hexdigest(nonce)
    session.expires_at = Time.current + Gateway::REFRESH_TOKEN_EXPIRES
    session.save!
    {
      access_token: issue(user, type: "access", expires_in: Gateway::ACCESS_TOKEN_EXPIRES, sid: session.id),
      refresh_token: issue(user, type: "refresh", expires_in: Gateway::REFRESH_TOKEN_EXPIRES, sid: session.id, jti: nonce),
      token_type: "bearer"
    }
  end

  def active_session(payload)
    return nil if payload["sid"].blank?
    session = AuthSession.find_by(id: payload["sid"], user_id: payload["sub"])
    session if session&.active?
  end

  def rotate(user, payload)
    session = active_session(payload)
    return nil unless session && payload["jti"].present?

    session.with_lock do
      return nil unless session.active?
      expected = Digest::SHA256.hexdigest(payload["jti"])
      return nil unless ActiveSupport::SecurityUtils.secure_compare(session.refresh_digest, expected)
      issue_token_pair(user, session: session)
    end
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
  def issue(user, type:, expires_in:, sid:, jti: nil)
    now = Time.now.to_i
    payload = {
      "sub" => user.id.to_s,
      "role" => user.role,
      "exp" => now + expires_in.to_i,
      "iat" => now,
      "type" => type,
      "sid" => sid,
      "jti" => jti
    }
    JWT.encode(payload, Gateway::JWT_SECRET_KEY, Gateway::JWT_ALGORITHM)
  end
  private_class_method :issue
end