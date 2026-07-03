#!/bin/bash
# Sunucuyu LaunchAgent ile çalıştır + tarayıcı aç
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK_DIR="$HOME/tl-yatirim-asistani"
if [[ -L "$LINK_DIR" ]] || [[ -d "$LINK_DIR" ]]; then
  PROJECT_DIR="$LINK_DIR"
else
  PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PORT=8502
URL="http://127.0.0.1:${PORT}"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.streamlit.plist"
LOG="$APP_SUPPORT/streamlit.log"
mkdir -p "$APP_SUPPORT"

server_running() {
  curl -sf "$URL/_stcore/health" >/dev/null 2>&1
}

ensure_agent() {
  if [[ ! -f "$PLIST" ]]; then
    osascript -e "display alert \"TL Yatırım Asistanı\" message \"İlk kurulum gerekli. Terminalde: bash macos/kurulum.sh\" as critical" 2>/dev/null || true
    exit 1
  fi
  UID_NUM="$(id -u)"
  if ! launchctl print "gui/${UID_NUM}/tr.yatirim.asistani.streamlit" >/dev/null 2>&1; then
    launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
  fi
  if ! server_running; then
    launchctl kickstart "gui/${UID_NUM}/tr.yatirim.asistani.streamlit" 2>/dev/null || true
  fi
}

wait_for_server() {
  for _ in $(seq 1 60); do
    if server_running; then
      sleep 1
      return 0
    fi
    sleep 1
  done
  osascript -e "display alert \"TL Yatırım Asistanı\" message \"Sunucu başlatılamadı. Log: ${LOG}\" as critical" 2>/dev/null || true
  exit 1
}

open_app_window() {
  if [[ -d "/Applications/Google Chrome.app" ]]; then
    open -a "Google Chrome" "$URL"
  elif [[ -d "/Applications/Safari.app" ]]; then
    open -a "Safari" "$URL"
  else
    open "$URL"
  fi
}

ensure_agent
wait_for_server
open_app_window
