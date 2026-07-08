#!/bin/bash
# LaunchAgent giriş noktası — önce senkron, sonra Streamlit (Application Support kopyası)
PROJECT_DIR="__PROJECT_DIR__"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PYTHON="__PYTHON__"
SOURCE_FILE="$APP_SUPPORT/source_path"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="$PROJECT_DIR"

# Kaynak (Desktop) → project/ senkronu
if [[ -f "$SOURCE_FILE" ]]; then
  SRC="$(tr -d '\n' < "$SOURCE_FILE")"
  if [[ -x "$SRC/macos/proje_sync.sh" ]]; then
    bash "$SRC/macos/proje_sync.sh" "$SRC"
  elif [[ -x "$PROJECT_DIR/macos/proje_sync.sh" ]]; then
    bash "$PROJECT_DIR/macos/proje_sync.sh"
  fi
fi

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

cd "$PROJECT_DIR" || exit 1
exec "$PYTHON" -m streamlit run app.py \
  --server.port 8502 \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.fileWatcherType none
