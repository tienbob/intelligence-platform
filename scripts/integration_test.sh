#!/usr/bin/env bash
# Migration/upsert integration test harness (IMPROVEMENT_PLAN.md Phase 3).
#
# Starts a throwaway Postgres (pgvector) container, applies all Alembic
# migrations from scratch, then runs tests/integration against the migrated
# schema. Exercising the *real* schema is what unit tests (which mock the DB)
# cannot do — this is the net that catches constraint <-> ON CONFLICT drift
# like the 0015 hotfix.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/intelligence-platform-stock"
PORT="${IT_PORT:-55432}"
CONTAINER="ip_integration_${BUILD_ID:-local}"

echo "[it] Starting throwaway Postgres on :$PORT ..."
docker run -d --rm --name "$CONTAINER" -p "$PORT:5432" \
  -e POSTGRES_PASSWORD=it -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=intelligence_stock \
  pgvector/pgvector:pg16 > /dev/null

cleanup() {
  docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
}
trap cleanup EXIT

# Wait for readiness
echo -n "[it] Waiting for postgres"
for i in $(seq 1 30); do
  if docker exec "$CONTAINER" pg_isready -U postgres > /dev/null 2>&1; then
    echo " ready"
    break
  fi
  sleep 1
  echo -n "."
done
if ! docker exec "$CONTAINER" pg_isready -U postgres > /dev/null 2>&1; then
  echo " FATAL: postgres did not become ready" >&2
  exit 1
fi

export DATABASE_URL="postgresql+asyncpg://postgres:it@localhost:$PORT/intelligence_stock"

cd "$APP"

# CI installs into the system interpreter; local dev uses .venv (if present).
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"; ALEMBIC=".venv/bin/alembic"
else
  PY="python"; ALEMBIC="alembic"
fi

echo "[it] Applying Alembic migrations to head ..."
"$ALEMBIC" upgrade head

echo "[it] Running integration tests ..."
"$PY" -m pytest tests/integration -q -m integration

echo "[it] PASS"