#!/bin/bash
# Kısa mom haftalık izleme — Mac açıkken her Pazartesi 10:00
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.shortmom.plist"
SYNC_SCRIPT="$APP_SUPPORT/short_mom_monitor_sync.sh"

bash "$SCRIPT_DIR/proje_sync.sh" "$REAL_DIR"
mkdir -p "$APP_SUPPORT"

cat > "$SYNC_SCRIPT" <<'EOF'
#!/bin/bash
set -euo pipefail
APP_SUPPORT="${APP_SUPPORT:-$HOME/Library/Application Support/TLYatirimAsistani}"
PROJ="$APP_SUPPORT/project"
LOG="$APP_SUPPORT/short_mom_monitor.log"
cd "$PROJ"
{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') short-mom monitor ===="
  /usr/bin/env python3 scripts/monitor_short_mom_live.py
  EC=$?
  echo "exit=$EC"
  if [[ "$EC" -eq 2 ]]; then
    echo "ROLLBACK ÖNERİSİ: short_momentum.enabled: false"
    # macOS bildirim (opsiyonel)
    osascript -e 'display notification "Kısa mom whipsaw eşiği aşıldı — enabled:false düşün" with title "TL Yatırım Asistanı"' 2>/dev/null || true
  fi
} >>"$LOG" 2>&1
EOF
chmod +x "$SYNC_SCRIPT"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tr.yatirim.asistani.shortmom</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SYNC_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${APP_SUPPORT}/project</string>
  <key>StandardOutPath</key>
  <string>${APP_SUPPORT}/short_mom_monitor.log</string>
  <key>StandardErrorPath</key>
  <string>${APP_SUPPORT}/short_mom_monitor.log</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
echo "[short_mom_monitor] Her Pazartesi 10:00 izleme aktif (Mac açıkken)."
echo "Log: $APP_SUPPORT/short_mom_monitor.log"
echo "Manuel: python3 scripts/monitor_short_mom_live.py"
echo "GitHub: .github/workflows/short-mom-monitor.yml (Mac kapalıyken de)"
