#!/bin/bash
# LaunchAgent giriş noktası — proje Application Support içinde (Desktop sandbox dışı)
PROJECT_DIR="__PROJECT_DIR__"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PYTHON="__PYTHON__"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="$PROJECT_DIR"

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
