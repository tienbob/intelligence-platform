# frozen_string_literal: true

require "uri"

# Single source of truth for the public app domain (root .env / compose):
#
#   APP_URL    — full public origin, e.g. https://app.example.com
#   APP_DOMAIN — its host[:port] slice, e.g. app.example.com
#
# Wired into the places that previously hardcoded or omitted the domain:
#   1. Host Authorization allow-list — the generated config/environments files
#      ship `config.hosts` commented out, so production ran with NO Host-header
#      (DNS-rebinding) protection unless a deployment enabled it by hand. Rails
#      skips the middleware entirely while config.hosts is empty, so adding the
#      configured domain here turns the protection on (and scopes it).
#   2. ActionMailer link generation — production.rb's placeholder
#      `{ host: "example.com" }` is overridden with the real origin.
#   3. CORS — config/initializers/cors.rb derives its default origin from
#      APP_URL when CORS_ALLOWED_ORIGINS is unset.
#
# Both variables are optional: unset/empty leaves every default above exactly
# as it was (empty config.hosts → middleware skipped, mailer placeholder kept).

app_url = ENV["APP_URL"].to_s.strip
app_domain = ENV["APP_DOMAIN"].to_s.strip

unless app_domain.empty?
  # Exact host[:port] plus the subdomain form — a leading "." tells Rails to
  # match any subdomain of the configured domain as well.
  Rails.application.config.hosts << app_domain
  Rails.application.config.hosts << ".#{app_domain}"
end

unless app_url.empty?
  begin
    uri = URI.parse(app_url)
    raise URI::InvalidURIError unless uri.host

    Rails.application.config.action_mailer.default_url_options = {
      host: uri.host,
      protocol: uri.scheme || "http",
    }
  rescue URI::InvalidURIError
    # Unparseable APP_URL — keep the host-only form so link generation
    # stays usable instead of silently regressing to "example.com".
    Rails.application.config.action_mailer.default_url_options = { host: app_domain } unless app_domain.empty?
  end
end
