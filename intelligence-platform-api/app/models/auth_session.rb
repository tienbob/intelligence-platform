# frozen_string_literal: true
class AuthSession < ApplicationRecord
  belongs_to :user

  def active?
    revoked_at.nil? && expires_at > Time.current
  end
end
