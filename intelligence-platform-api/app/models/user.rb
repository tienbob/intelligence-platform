# frozen_string_literal: true

# Rails-owned system-of-record for users.
#
# Uses Devise for authentication (database_authenticatable works with the
# `encrypted_password` column). The `users` table was originally created with
# `password_hash` (Python/FastAPI schema) and was renamed to `encrypted_password`
# to align with Devise.
class User < ApplicationRecord
  # Include default devise modules. Others available are:
  # :confirmable, :lockable, :timeoutable, :trackable and :omniauthable
  devise :database_authenticatable, :registerable,
         :recoverable, :rememberable, :validatable

  ROLES = %w[USER ANALYST ADMIN SYSTEM].freeze

  # ── Validations ────────────────────────────────────────────────
  validates :name, presence: true
  validates :role, inclusion: { in: ROLES }, allow_nil: true

  # ── Callbacks ─────────────────────────────────────────────────
  before_validation :normalize_email

  # ── Role helpers (mirrors Python Role hierarchy) ───────────────
  def admin?
    role == "ADMIN" || role == "SYSTEM"
  end

  def analyst?
    %w[ANALYST ADMIN SYSTEM].include?(role)
  end

  private

  def normalize_email
    self.email = email.to_s.strip.downcase if email.present?
  end
end