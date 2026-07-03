#!/bin/bash
# Streamlit sunucusunu LaunchAgent olarak kur — Desktop sandbox hatasını çözer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/TLYatirimAsistani"
SYNC_DIR="$APP_SUPPORT/project"
PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.streamlit.plist"
WRAPPER="$APP_SUPPORT/streamlit_wrapper.sh"
mkdir -p "$APP_SUPPORT"

echo "Proje kopyalanıyor → $SYNC_DIR"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'node_modules/' \
  "$REAL_DIR/" "$SYNC_DIR/"

PROJECT_DIR="$SYNC_DIR"

PYTHON=""
for candidate in \
  "/opt/homebrew/bin/python3" \
  "/usr/local/bin/python3" \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "HATA: python3 bulunamadı."
  exit 1
fi

sed -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" -e "s|__PYTHON__|${PYTHON}|g" \
  "$SCRIPT_DIR/streamlit_wrapper.sh" > "$WRAPPER"
chmod +x "$WRAPPER"

LOG="$APP_SUPPORT/streamlit.log"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tr.yatirim.asistani.streamlit</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${WRAPPER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"

# CDS günlük senkron (18:00 — piyasa kapanışı sonrası)
CDS_PLIST="$HOME/Library/LaunchAgents/tr.yatirim.asistani.cds.plist"
CDS_SCRIPT="$APP_SUPPORT/cds_sync.sh"
sed -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" -e "s|__PYTHON__|${PYTHON}|g" \
  "$SCRIPT_DIR/cds_sync.sh" > "$CDS_SCRIPT"
chmod +x "$CDS_SCRIPT"

cat > "$CDS_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tr.yatirim.asistani.cds</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${CDS_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>StandardOutPath</key>
  <string>${APP_SUPPORT}/cds_sync.log</string>
  <key>StandardErrorPath</key>
  <string>${APP_SUPPORT}/cds_sync.log</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>18</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/${UID_NUM}" "$CDS_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$CDS_PLIST" 2>/dev/null || true

for _ in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8502/_stcore/health" >/dev/null 2>&1; then
    echo "Sunucu hazır: http://127.0.0.1:8502"
    exit 0
  fi
  sleep 1
done
echo "Sunucu henüz yanıt vermiyor — log: $LOG"
tail -25 "$LOG" 2>/dev/null || true
exit 1
