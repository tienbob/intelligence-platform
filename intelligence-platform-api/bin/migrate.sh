#!/bin/bash
set -euo pipefail

# Python owns the shared schema baseline. Rails db:prepare/db:migrate can
# initialize an unregistered database from stale schema.rb with force:cascade.
# Invoke migration context directly: apply migrations, never reload the schema.
bundle exec rails runner 'ActiveRecord::Base.connection_pool.migration_context.migrate'
