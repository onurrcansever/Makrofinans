#!/bin/bash
# AL/SAT değişim alarmı — Mac açıkken her 30 dk (--sinyal-alarm)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.sinyal.plist"
ALARM_SCRIPT="$APP_SUPPORT/alarm_sync.sh"

bash "$SCRIPT_DIR/proje_sync.sh" "$REAL_DIR"
mkdir -p "$APP_SUPPORT"
cp "$SCRIPT_DIR/alarm_sync.sh" "$ALARM_SCRIPT"
chmod +x "$ALARM_SCRIPT"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tr.yatirim.asistani.sinyal</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ALARM_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${APP_SUPPORT}/project</string>
  <key>StandardOutPath</key>
  <string>${APP_SUPPORT}/alarm_sync.log</string>
  <key>StandardErrorPath</key>
  <string>${APP_SUPPORT}/alarm_sync.log</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
echo "[sinyal_alarm_kurulum] Her 30 dk AL/SAT değişim kontrolü aktif (Mac açıkken)."
echo "Log: $APP_SUPPORT/alarm_sync.log"
echo "Günlük özet istemezseniz .env: OZET_ALARM_HER_ZAMAN=0"
