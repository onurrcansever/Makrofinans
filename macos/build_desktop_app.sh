#!/bin/bash
# Mac masaüstü .app oluşturur — çıktı: ~/Desktop/TL Yatirim Asistani.app
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="TL Yatirim Asistani.app"
DESKTOP="$HOME/Desktop"
APP_PATH="$DESKTOP/$APP_NAME"
TMP_AS="$SCRIPT_DIR/.launcher_build.applescript"

echo "Proje: $PROJECT_DIR"
echo "Hedef: $APP_PATH"

chmod +x "$SCRIPT_DIR/launcher_inner.sh" "$SCRIPT_DIR/durdur.sh"

sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$SCRIPT_DIR/launcher.applescript" > "$TMP_AS"
rm -rf "$APP_PATH"
osacompile -o "$APP_PATH" "$TMP_AS"
rm -f "$TMP_AS"

# Dock / Launchpad için kopya (isteğe bağlı — masaüstünde zaten var)
echo ""
echo "Tamam: $APP_PATH"
echo "Masaüstündeki uygulamaya çift tıklayın."
echo "Durdurmak için: macos/durdur.sh"
echo "Log: ~/Library/Application Support/TLYatirimAsistani/streamlit.log"
