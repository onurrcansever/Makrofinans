#!/bin/bash
# Sessiz fiyat + analist önbellek — Mac açıkken her 15 dk
set -euo pipefail

APP_SUPPORT="${APP_SUPPORT:-$HOME/Library/Application Support/TLYatirimAsistani}"
PROJECT="${PROJECT:-$APP_SUPPORT/project}"
LOG="$APP_SUPPORT/cache_refresh.log"

mkdir -p "$APP_SUPPORT"
cd "$PROJECT"

if [[ -f "$PROJECT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT/.env"
  set +a
fi

PYTHON="${PYTHON:-python3}"
if [[ -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') cache_refresh_sync ==="
  "$PYTHON" scripts/background_cache_refresh.py 2>&1 || \
    "$PYTHON" main.py --cache-yenile 2>&1 || true
} >> "$LOG" 2>&1
