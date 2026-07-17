#!/usr/bin/env bash
# GitHub Actions — secret'lardan yerel veri dosyalarını geri yükle.
set -euo pipefail

_restore() {
  local secret_val="$1"
  local dest="$2"
  local label="$3"
  if [[ -z "$secret_val" ]]; then
    echo "  ⚠ $label secret yok — atlandı"
    return 0
  fi
  echo "$secret_val" | base64 -d > "$dest"
  echo "  ✓ $dest ($(wc -c < "$dest" | tr -d ' ') byte)"
}

echo "=== GitHub CI veri geri yükleme ==="
_restore "${VARLIKLARIM_JSON:-}" ".varliklarim.json" "VARLIKLARIM_JSON"
_restore "${TEMEL_VERI_CACHE_JSON:-}" ".temel_veri_cache.json" "TEMEL_VERI_CACHE_JSON"
_restore "${PORTFOY_YORUM_CACHE_JSON:-}" ".portfoy_yorum_cache.json" "PORTFOY_YORUM_CACHE_JSON"

if [[ ! -f .varliklarim.json ]]; then
  echo "::warning::.varliklarim.json yok — WhatsApp pozisyon tablosu boş kalır. Mac'te: python3 scripts/portfoy_github_sync.py"
fi
