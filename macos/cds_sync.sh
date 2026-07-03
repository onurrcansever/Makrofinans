#!/bin/bash
# Günlük CDS kaynak senkronu — LaunchAgent veya cron ile çalıştırın
set -euo pipefail

APP_SUPPORT="${HOME}/Library/Application Support/TLYatirimAsistani"
PROJECT_DIR="${APP_SUPPORT}/project"
LOG="${APP_SUPPORT}/cds_sync.log"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "$(date -Iseconds) Proje yok — önce bash macos/kurulum.sh" >> "$LOG"
  exit 1
fi

PYTHON=""
for candidate in \
  "/opt/homebrew/bin/python3" \
  "/usr/local/bin/python3" \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done

{
  echo "=== $(date -Iseconds) CDS sync ==="
  cd "$PROJECT_DIR"
  "$PYTHON" main.py --cds-guncelle --cds-guncelle-bildir 2>&1 || true
} >> "$LOG" 2>&1
