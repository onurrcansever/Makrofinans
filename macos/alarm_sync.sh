#!/bin/bash
# Makrofinans WhatsApp alarmları — günlük özet (10:00 / 13:00 / 15:00 / 18:00 TR)
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
export OZET_ALARM_HER_ZAMAN="${OZET_ALARM_HER_ZAMAN:-1}"

PYTHON="${PYTHON:-python3}"
if [[ -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') alarm_sync ==="
  "$PYTHON" main.py --ozet-alarm --notify 2>&1 || true
} >> "$LOG" 2>&1
