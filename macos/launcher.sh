#!/bin/bash
# TL Yatırım Asistanı — masaüstü başlatıcı (Streamlit + uygulama penceresi)
set -euo pipefail

APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
mkdir -p "$APP_SUPPORT"

# build_desktop_app.sh bu satırı proje yolu ile değiştirir
PROJECT_DIR="__PROJECT_DIR__"
PORT=8502
URL="http://127.0.0.1:${PORT}"
LOG="$APP_SUPPORT/streamlit.log"
PIDFILE="$APP_SUPPORT/streamlit.pid"

PYTHON=""
for candidate in \
  "/usr/local/bin/python3" \
  "/opt/homebrew/bin/python3" \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  osascript -e 'display alert "TL Yatırım Asistanı" message "python3 bulunamadı. Terminal: xcode-select --install veya Homebrew python3 kurun." as critical'
  exit 1
fi

cd "$PROJECT_DIR"

server_running() {
  lsof -ti ":$PORT" >/dev/null 2>&1
}

start_server() {
  if server_running; then
    return 0
  fi
  echo "[$(date)] Streamlit başlatılıyor..." >> "$LOG"
  nohup "$PYTHON" -m streamlit run app.py \
    --server.port "$PORT" \
    --server.headless true \
    >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"

  for _ in $(seq 1 45); do
    if curl -sf "$URL/_stcore/health" >/dev/null 2>&1 || curl -sf "$URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  osascript -e 'display alert "TL Yatırım Asistanı" message "Sunucu başlatılamadı. Log: '"$LOG"'" as critical'
  exit 1
}

open_app_window() {
  if [[ -d "/Applications/Google Chrome.app" ]]; then
    open -na "Google Chrome" --args --app="$URL"
  elif [[ -d "/Applications/Microsoft Edge.app" ]]; then
    open -na "Microsoft Edge" --args --app="$URL"
  elif [[ -d "/Applications/Arc.app" ]]; then
    open -a "Arc" "$URL"
  else
    open "$URL"
  fi
}

start_server
open_app_window
