# frozen_string_literal: true

# Authentication + authorization concern for the API gateway.
#
# Mirrors the Python FastAPI behavior:
#   - When AUTH_ENABLED is false → returns an anonymous SYSTEM context (open API).
#   - When AUTH_ENABLED is true  → requires a valid Bearer access token.
#
# Provides `current_user`, `authenticate_request!`, and role helpers.
module Authenticatable
  extend ActiveSupport::Concern

  included do
    before_action :authenticate_request!
  end

  private

  # Returns the authenticated User, or raises 401.
  def authenticate_request!
    return anonymous_context unless Gateway::AUTH_ENABLED

    token = bearer_token
    raise AuthenticationError unless token

    payload = JwtService.decode_safe(token)
    raise AuthenticationError if payload.nil? || payload["type"] != "access"

    raise AuthenticationError unless JwtService.active_session(payload)

    @current_user = User.find_by(id: payload["sub"])
    raise AuthenticationError unless @current_user&.is_active?

    @current_user
  end

  def current_user
    @current_user ||= anonymous_context
  end

  def bearer_token
    header = request.headers["Authorization"]
    return nil if header.blank?

    scheme, token = header.split(" ")
    token if scheme&.casecmp("bearer")&.zero? && token.present?
  end

  def anonymous_context
    @anonymous_context ||= AnonymousUser.new
  end

  def require_role!(*roles)
    return true unless Gateway::AUTH_ENABLED
    return true if roles.include?(current_user.role)

    raise ForbiddenError
  end

  # ── Errors ─────────────────────────────────────────────────────
  class AuthenticationError < StandardError; end
  class ForbiddenError < StandardError; end

  # Anonymous user used when AUTH_ENABLED is false (dev mode), matching
  # Python's SYSTEM context.
  class AnonymousUser
    def id = nil
    def role = "SYSTEM"
    def is_active? = true
    def admin? = true
    def analyst? = true
  end
end