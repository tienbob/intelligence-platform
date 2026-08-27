# frozen_string_literal: true

module Api
  module V1
    # Authentication endpoints — Rails-owned system of record.
    #
    #   POST /api/v1/auth/register  → 201 { access_token, refresh_token, token_type }
    #   POST /api/v1/auth/login     → 200 { access_token, refresh_token, token_type }
    #   POST /api/v1/auth/refresh   → 200 { access_token, refresh_token, token_type }
    #   GET  /api/v1/auth/me        → 200 { id, email, name, role, is_active, ... }
    class AuthController < BaseController
      skip_before_action :authenticate_request!, only: %i[register login refresh]

      # POST /auth/register
      def register
        if User.exists?(email: params[:email].to_s.strip.downcase)
          render json: { detail: "A user with this email already exists" }, status: :conflict
          return
        end

        user = User.new(
          email: params[:email],
          password: params[:password],
          name: params[:name],
          role: "USER"
        )
        user.save!
        render json: JwtService.issue_token_pair(user), status: :created
      rescue ActiveRecord::RecordNotUnique
        render json: { detail: "A user with this email already exists" }, status: :conflict
      end

      # POST /auth/login
      def login
        user = User.find_by(email: params[:email].to_s.strip.downcase)
        # Devise's database_authenticatable provides valid_password?
        if user&.is_active? && user.valid_password?(params[:password])
          render json: JwtService.issue_token_pair(user)
        else
          render json: { detail: "Invalid email or password" }, status: :unauthorized
        end
      end

      # POST /auth/refresh
      def refresh
        payload = JwtService.decode_safe(params[:refresh_token])
        raise Authenticatable::AuthenticationError if payload.nil? || payload["type"] != "refresh"

        user = User.find_by(id: payload["sub"])
        raise Authenticatable::AuthenticationError if user.nil? || !user.is_active?

        render json: JwtService.issue_token_pair(user)
      end

      # GET /auth/me
      def me
        user = current_user
        if user.is_a?(Authenticatable::AnonymousUser)
          render json: { detail: "Not authenticated" }, status: :unauthorized
          return
        end

        render json: user.as_json(only: %i[id email name role is_active created_at updated_at])
      end
    end
  end
end