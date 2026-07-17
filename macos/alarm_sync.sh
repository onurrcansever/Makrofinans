#!/bin/bash
# Makrofinans WhatsApp — AL değişince anında (--sinyal-alarm); isteğe bağlı günlük özet
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
export OZET_ALARM_HER_ZAMAN="${OZET_ALARM_HER_ZAMAN:-0}"

PYTHON="${PYTHON:-python3}"
if [[ -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') alarm_sync ==="
  # Yalnızca AL/SAT değişince mesaj (İZLE dahil değil)
  "$PYTHON" main.py --sinyal-alarm --notify 2>&1 || true
  if [[ "${OZET_ALARM_HER_ZAMAN}" == "1" ]]; then
    "$PYTHON" main.py --ozet-alarm --notify 2>&1 || true
  fi
  # GitHub Actions için portföy secret güncelle (GITHUB_TOKEN varsa)
  if [[ -n "${GITHUB_TOKEN:-}${GITHUB_PAT:-}" ]]; then
    "$PYTHON" scripts/portfoy_github_sync.py 2>&1 || true
  fi
} >> "$LOG" 2>&1
