#!/bin/bash
# Desktop (kaynak) proje → Application Support kopyası — LaunchAgent buradan çalışır.
set -euo pipefail

APP_SUPPORT="${APP_SUPPORT:-$HOME/Library/Application Support/TLYatirimAsistani}"
SYNC_DIR="$APP_SUPPORT/project"
SOURCE_FILE="$APP_SUPPORT/source_path"

SOURCE_DIR="${1:-}"
if [[ -z "$SOURCE_DIR" && -f "$SOURCE_FILE" ]]; then
  SOURCE_DIR="$(tr -d '\n' < "$SOURCE_FILE")"
fi
if [[ -z "$SOURCE_DIR" ]]; then
  for d in \
    "$HOME/Desktop/tl-yatirim-asistani" \
    "$HOME/tl-yatirim-asistani" \
    "$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"; do
    if [[ -f "$d/app.py" ]]; then
      SOURCE_DIR="$d"
      break
    fi
  done
fi

if [[ ! -f "${SOURCE_DIR}/app.py" ]]; then
  echo "[proje_sync] Kaynak proje bulunamadı (${SOURCE_DIR:-boş})" >&2
  exit 0
fi

mkdir -p "$APP_SUPPORT" "$SYNC_DIR"
printf '%s\n' "$SOURCE_DIR" > "$SOURCE_FILE"

rsync -a --delete \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'node_modules/' \
  --exclude '.girdi_onay_state.json' \
  --exclude '.signal_state.json' \
  --exclude '.varliklarim.json' \
  --exclude 'manual_inputs.json' \
  --exclude 'market_cache.db' \
  --exclude 'cds_history.jsonl' \
  "$SOURCE_DIR/" "$SYNC_DIR/"

echo "[proje_sync] $(date '+%Y-%m-%d %H:%M:%S') ← $SOURCE_DIR"
