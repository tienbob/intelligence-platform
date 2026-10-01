raise 'wrong database' unless ActiveRecord::Base.connection.current_database.start_with?('audit_verify_')
user = User.create!(email: "audit-#{SecureRandom.hex(6)}@example.invalid", name: 'Audit', password: SecureRandom.hex(20), role: 'USER', is_active: true)
pair = JwtService.issue_token_pair(user)
payload = JwtService.decode(pair[:refresh_token])
results = 2.times.map { Thread.new { ActiveRecord::Base.connection_pool.with_connection { JwtService.rotate(user, payload) } } }.map(&:value)
raise 'rotation race' unless results.compact.size == 1
raise 'replay accepted' if JwtService.rotate(user, payload)
access = JwtService.decode(results.compact.first[:access_token])
session = JwtService.active_session(access)
raise 'missing session' unless session
session.update!(revoked_at: Time.current)
raise 'revocation failed' if JwtService.active_session(access)
key = "audit:#{SecureRandom.hex(12)}"
allowed = 12.times.map { Thread.new { ActiveRecord::Base.connection_pool.with_connection { AuthThrottle.allow?(key, limit: 3) } } }.map(&:value)
raise 'throttle race' unless allowed.count(true) == 3
puts 'PASS: PostgreSQL refresh rotation concurrency, replay rejection, session revocation, shared auth throttle'
