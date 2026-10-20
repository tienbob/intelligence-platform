#!/usr/bin/env bash
# Restore drill — proves the latest backup is actually restorable into a clean
# throwaway pgvector container (never the primary). IMPROVEMENT_PLAN.md Phase 0.2.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-$HOME/db-backups}"
CONTAINER_NAME="ip_drill_$$"  # unique name to avoid clashes

echo "[drill] Using backup dir: $BACKUP_DIR"
LATEST=$(ls -1t "$BACKUP_DIR/daily"/*.dump 2>/dev/null | head -1)
if [ -z "${LATEST:-}" ]; then
  echo "[drill] FATAL: no daily backups found in $BACKUP_DIR/daily" >&2
  exit 1
fi
echo "[drill] Restoring: $LATEST"

# throwaway pgvector instance
docker run -d --rm --name "$CONTAINER_NAME" \
  -v "$LATEST:/tmp/drill.dump:ro" \
  -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=intelligence_stock \
  pgvector/pgvector:pg16 > /dev/null
trap 'docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true' EXIT

echo "[drill] Waiting for postgres to be ready..."
for i in $(seq 1 30); do
  if docker exec "$CONTAINER_NAME" pg_isready -U postgres > /dev/null 2>&1; then break; fi
  sleep 1
done

echo "[drill] Restoring database..."
# pg_restore/psql run inside the container — no host postgres client needed.
docker exec "$CONTAINER_NAME" pg_restore -U postgres -d intelligence_stock \
  --no-owner --no-privileges /tmp/drill.dump

echo "[drill] Verifying row counts..."
RESULT=$(docker exec "$CONTAINER_NAME" psql -U postgres -d intelligence_stock -tAc "
  SELECT (SELECT COUNT(*) FROM companies) > 0
     AND (SELECT COUNT(*) FROM news) > 0;")

if [ "$RESULT" = "t" ]; then
  echo "[drill] PASS: Restore verified."
  exit 0
else
  echo "[drill] FAIL: Verification queries returned false." >&2
  exit 1
fi