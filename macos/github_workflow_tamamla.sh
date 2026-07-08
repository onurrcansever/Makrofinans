#!/bin/bash
# GitHub'a workflow dosyasını push et — token'da "workflow" izni olmalı.
set -euo pipefail

REPO="https://github.com/onurrcansever/Makrofinans.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " GitHub alarm programı (Mac kapalıyken WhatsApp)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1) Tarayıcıda token oluşturun — 'workflow' kutusu işaretli olsun:"
open "https://github.com/settings/tokens/new?scopes=repo,workflow&description=Makrofinans-Alarm" 2>/dev/null || true
echo "   https://github.com/settings/tokens/new?scopes=repo,workflow"
echo ""
read -rsp "2) Yeni token'ı yapıştırın (ekranda görünmez): " TOKEN
echo ""
echo ""

cd "$ROOT"
git add .github/workflows/gunluk-rapor.yml 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -m "GitHub Actions alarm — 09:00 ve 16:30 TR WhatsApp"
fi

if git push "https://x-access-token:${TOKEN}@${REPO#https://}" main; then
  echo ""
  echo "✓ Workflow yüklendi."
  echo "  Actions → Makrofinans Alarmları → Run workflow"
  open "https://github.com/onurrcansever/Makrofinans/actions" 2>/dev/null || true
else
  echo "Push başarısız — token'da repo + workflow izni var mı?"
  exit 1
fi
