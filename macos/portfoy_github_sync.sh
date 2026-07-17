#!/bin/bash
# Yerel .varliklarim.json → GitHub Actions secret (WhatsApp eksiksiz pozisyon tablosu)
set -euo pipefail

APP_SUPPORT="${APP_SUPPORT:-$HOME/Library/Application Support/TLYatirimAsistani}"
SOURCE_FILE="$APP_SUPPORT/source_path"
SOURCE_DIR=""

if [[ -f "$SOURCE_FILE" ]]; then
  SOURCE_DIR="$(tr -d '\n' < "$SOURCE_FILE")"
fi
if [[ -z "$SOURCE_DIR" || ! -f "$SOURCE_DIR/app.py" ]]; then
  SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

cd "$SOURCE_DIR"

if [[ -f "$SOURCE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SOURCE_DIR/.env"
  set +a
fi

PYTHON="${PYTHON:-python3}"
if [[ -x "$SOURCE_DIR/.venv/bin/python" ]]; then
  PYTHON="$SOURCE_DIR/.venv/bin/python"
fi

echo "[portfoy_github_sync] $(date '+%Y-%m-%d %H:%M:%S')"
"$PYTHON" scripts/portfoy_github_sync.py "$@"
