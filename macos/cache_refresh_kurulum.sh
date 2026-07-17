#!/bin/bash
# Sessiz cache yenileme — Mac açıkken her 15 dk (fiyat ≤15 dk + analist)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.cache.plist"
SYNC_SCRIPT="$APP_SUPPORT/cache_refresh_sync.sh"

bash "$SCRIPT_DIR/proje_sync.sh" "$REAL_DIR"
mkdir -p "$APP_SUPPORT"
cp "$SCRIPT_DIR/cache_refresh_sync.sh" "$SYNC_SCRIPT"
chmod +x "$SYNC_SCRIPT"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tr.yatirim.asistani.cache</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SYNC_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${APP_SUPPORT}/project</string>
  <key>StandardOutPath</key>
  <string>${APP_SUPPORT}/cache_refresh.log</string>
  <key>StandardErrorPath</key>
  <string>${APP_SUPPORT}/cache_refresh.log</string>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
echo "[cache_refresh_kurulum] Her 15 dk sessiz fiyat+analist yenileme aktif (Mac açıkken)."
echo "Log: $APP_SUPPORT/cache_refresh.log"
echo "Manuel: python scripts/background_cache_refresh.py"
