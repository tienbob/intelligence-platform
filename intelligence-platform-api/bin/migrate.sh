#!/bin/bash
set -e

# Skip if all migrations are already applied.
# This avoids unnecessary work on every container start.
# If the DB doesn't exist yet, db:migrate:status fails — that's fine,
# we just proceed to db:prepare which creates the DB and runs migrations.
STATUS=$(bundle exec rails db:migrate:status 2>/dev/null || true)

if [ -n "$STATUS" ] && ! echo "$STATUS" | grep -q "down"; then
  echo "Migrations already up to date. Skipping."
  exit 0
fi

echo "Running Rails migrations..."
bundle exec rails db:prepare
