#!/usr/bin/env bash
# Nightly logical backup, custom format (compressed + restorable-selective).
# IMPROVEMENT_PLAN.md Phase 0 — I1 (P0: data-loss risk).
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-$HOME/db-backups}"
KEEP_DAILY="${KEEP_DAILY:-14}"; KEEP_WEEKLY="${KEEP_WEEKLY:-12}"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
cd "$(dirname "$0")/.."                      # compose project root
STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
OUT="$BACKUP_DIR/daily/intelligence_stock_${STAMP}.dump"
docker compose exec -T db pg_dump -U postgres -d intelligence_stock -Fc \
  > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"
docker compose exec -T db pg_restore --list < "$OUT" > /dev/null  # archive integrity check (in-container — no host client needed)
ls -1t "$BACKUP_DIR/daily"/*.dump | tail -n +"$((KEEP_DAILY + 1))" | xargs -r rm --
if [ "$(date -u +%u)" = "7" ]; then           # weekly copy on Sundays (UTC)
  cp "$OUT" "$BACKUP_DIR/weekly/"
  ls -1t "$BACKUP_DIR/weekly"/*.dump | tail -n +"$((KEEP_WEEKLY + 1))" | xargs -r rm --
fi
# Optional off-host hook: set BACKUP_REMOTE in the crontab env, e.g.
#   BACKUP_REMOTE="rclone copy '$OUT' remote:ip-backups/"
[ -n "${BACKUP_REMOTE:-}" ] && eval "$BACKUP_REMOTE"