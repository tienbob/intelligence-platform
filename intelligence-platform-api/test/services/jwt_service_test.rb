# Run: bundle exec ruby test/services/jwt_service_test.rb (no database needed).
require "minitest/autorun"
require "active_support/all"
require "monitor"
module Gateway
  JWT_SECRET_KEY = "test-only-key-which-is-not-used-outside-this-process"
  JWT_ALGORITHM = "HS256"
  ACCESS_TOKEN_EXPIRES = 30.minutes
  REFRESH_TOKEN_EXPIRES = 7.days
end
class AuthSession
  attr_accessor :id, :user_id, :refresh_digest, :expires_at, :revoked_at
  @rows = {}
  class << self
    attr_reader :rows
    def find_by(id:, user_id:)
      row = rows[id]
      row if row && row.user_id.to_s == user_id.to_s
    end
  end
  def initialize(id:, user_id:)
    @id, @user_id = id, user_id
    @lock = Monitor.new
  end
  def save! = self.class.rows[id] = self
  def active? = revoked_at.nil? && expires_at > Time.current
  def with_lock(&block) = @lock.synchronize(&block)
end
require_relative "../../app/services/jwt_service"
class JwtServiceTest < Minitest::Test
  def setup
    AuthSession.rows.clear
    @user = Struct.new(:id, :role).new(42, "USER")
  end
  def test_rotation_rejects_replay_and_keeps_session
    pair = JwtService.issue_token_pair(@user)
    payload = JwtService.decode(pair[:refresh_token])
    rotated = JwtService.rotate(@user, payload)
    refute_nil rotated
    assert_nil JwtService.rotate(@user, payload)
    assert_equal payload['sid'], JwtService.decode(rotated[:access_token])['sid']
    refute_equal pair[:refresh_token], rotated[:refresh_token]
  end
  def test_revoked_session_rejects_access_and_refresh
    pair = JwtService.issue_token_pair(@user)
    access = JwtService.decode(pair[:access_token])
    session = JwtService.active_session(access)
    session.revoked_at = Time.current
    assert_nil JwtService.active_session(access)
    assert_nil JwtService.rotate(@user, JwtService.decode(pair[:refresh_token]))
  end
  def test_legacy_and_other_user_sessions_rejected
    assert_nil JwtService.active_session({'sub' => '42'})
    pair = JwtService.issue_token_pair(@user)
    payload = JwtService.decode(pair[:access_token]).merge('sub' => '99')
    assert_nil JwtService.active_session(payload)
  end
  def test_concurrent_refresh_has_only_one_winner
    pair = JwtService.issue_token_pair(@user)
    payload = JwtService.decode(pair[:refresh_token])
    results = 2.times.map { Thread.new { JwtService.rotate(@user, payload) } }.map(&:value)
    assert_equal 1, results.compact.length
  end
end
