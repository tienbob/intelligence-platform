# frozen_string_literal: true
require "openssl"

# Atomic counters shared by all gateway processes. No passwords/tokens are stored.
class AuthThrottle
  def self.allow?(identity, limit:, window: 60)
    key = OpenSSL::HMAC.hexdigest("SHA256", Gateway::JWT_SECRET_KEY, identity)
    connection = ActiveRecord::Base.connection
    key_sql = connection.quote(key)
    result = connection.select_value(<<~SQL)
      INSERT INTO auth_throttles (key, attempts, expires_at)
      VALUES (#{key_sql}, 1, CURRENT_TIMESTAMP + #{Integer(window)} * INTERVAL '1 second')
      ON CONFLICT (key) DO UPDATE SET
        attempts = CASE WHEN auth_throttles.expires_at <= CURRENT_TIMESTAMP THEN 1 ELSE auth_throttles.attempts + 1 END,
        expires_at = CASE WHEN auth_throttles.expires_at <= CURRENT_TIMESTAMP
          THEN CURRENT_TIMESTAMP + #{Integer(window)} * INTERVAL '1 second' ELSE auth_throttles.expires_at END
      RETURNING attempts
    SQL
    # Bounded cleanup; expired counters are reusable even before cleanup runs.
    connection.execute(<<~SQL)
      DELETE FROM auth_throttles WHERE key IN
        (SELECT key FROM auth_throttles WHERE expires_at < CURRENT_TIMESTAMP - INTERVAL '1 day' LIMIT 100)
    SQL
    result.to_i <= limit
  end
end
