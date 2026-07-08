#!/bin/bash
# Makrofinans WhatsApp alarmları — rejim + hisse sinyali (09:00 / 16:30 TR)
set -euo pipefail

APP_SUPPORT="${APP_SUPPORT:-$HOME/Library/Application Support/TLYatirimAsistani}"
PROJECT="${PROJECT:-$APP_SUPPORT/project}"
LOG="$APP_SUPPORT/alarm_sync.log"

mkdir -p "$APP_SUPPORT"
cd "$PROJECT"

if [[ -f "$PROJECT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT/.env"
  set +a
fi

export BILDIRIM_KANALI="${BILDIRIM_KANALI:-whatsapp}"

PYTHON="${PYTHON:-python3}"
if [[ -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') alarm_sync ==="
  "$PYTHON" main.py --alert-only 2>&1 || true
  "$PYTHON" main.py --sinyal-alarm --notify 2>&1 || true
} >> "$LOG" 2>&1
