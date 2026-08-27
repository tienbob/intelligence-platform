# frozen_string_literal: true

class ApplicationController < ActionController::API
  include Authenticatable
  include Pundit::Authorization

  # Rescues authentication/forbidden errors raised by the Authenticatable concern.
  rescue_from Authenticatable::AuthenticationError do |_e|
    render json: { detail: "Not authenticated" }, status: :unauthorized
  end

  rescue_from Authenticatable::ForbiddenError do |_e|
    render json: { detail: "You do not have permission to perform this action" }, status: :forbidden
  end

  rescue_from Pundit::NotAuthorizedError do |_e|
    render json: { detail: "You do not have permission to perform this action" }, status: :forbidden
  end

  rescue_from ActiveRecord::RecordNotFound do |_e|
    render json: { detail: "Resource not found" }, status: :not_found
  end

  rescue_from ActiveRecord::RecordInvalid do |e|
    render json: { detail: e.record.errors.full_messages.join(", ") }, status: :unprocessable_entity
  end
end