#!/bin/bash
# WhatsApp alarm LaunchAgent — 09:00 ve 16:30 TR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.alarm.plist"
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
  <string>tr.yatirim.asistani.alarm</string>
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
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>9</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>16</integer>
      <key>Minute</key>
      <integer>30</integer>
    </dict>
  </array>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
echo "[alarm_kurulum] 09:00 ve 16:30 TR WhatsApp alarmları aktif."
echo "Log: $APP_SUPPORT/alarm_sync.log"
