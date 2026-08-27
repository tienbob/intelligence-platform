# syntax=docker/dockerfile:1
# Rails API gateway — Dockerfile

# ── Base stage ──────────────────────────────────────────────────
FROM ruby:3.3-slim AS base
LABEL org.opencontainers.image.title="Market Intelligence Rails API"
LABEL org.opencontainers.image.description="Rails API gateway for the Market Intelligence platform"

ENV RAILS_ENV=production \
    BUNDLE_DEPLOYMENT=1 \
    BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_WITHOUT=development:test

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      build-essential \
      libpq-dev \
      curl \
      passwd \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Build stage ─────────────────────────────────────────────────
FROM base AS build

COPY Gemfile Gemfile.lock ./
RUN bundle install

# Copy the application code
COPY . .

# ── Runtime stage ───────────────────────────────────────────────
FROM base AS final

ENV RAILS_LOG_TO_STDOUT=1 \
    RAILS_SERVE_STATIC_FILES=1

RUN groupadd --system rails --gid 1001 && \
    useradd --system --uid 1001 --gid rails --create-home --shell /bin/bash rails

# Copy installed gems and app from build stage
COPY --from=build /usr/local/bundle /usr/local/bundle
COPY --from=build /app /app

RUN chown -R rails:rails /app

USER rails

EXPOSE 3000

CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]