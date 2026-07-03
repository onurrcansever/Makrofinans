#!/bin/bash
# Streamlit LaunchAgent durdur
PORT=8502
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.streamlit.plist"
UID_NUM="$(id -u)"

if [[ -f "$PLIST" ]]; then
  launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
fi
lsof -ti ":$PORT" | xargs kill 2>/dev/null || true
rm -f "$HOME/Library/Application Support/TLYatirimAsistani/streamlit.pid"
echo "Streamlit durduruldu (port $PORT)."
