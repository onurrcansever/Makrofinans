#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yerel portföy + isteğe bağlı cache dosyalarını GitHub Actions secret'larına yükler.

GitHub Actions alarm workflow'ları bu secret'lardan .varliklarim.json vb. geri yükler;
WhatsApp özetinde pozisyon tablosu ve portföy yorumu eksiksiz çalışır.

Kullanım:
  export GITHUB_TOKEN=ghp_...   # repo + secrets izni
  python3 scripts/portfoy_github_sync.py

  # veya belirli dosya:
  python3 scripts/portfoy_github_sync.py --portfoy ~/Desktop/tl-yatirim-asistani/.varliklarim.json
"""
from typing import Optional
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from scripts.github_secrets_util import dosya_base64_yukle

# (secret adı, yerel dosya adı, zorunlu)
SYNC_DOSYALAR = (
    ("VARLIKLARIM_JSON", ".varliklarim.json", True),
    ("TEMEL_VERI_CACHE_JSON", ".temel_veri_cache.json", False),
    ("PORTFOY_YORUM_CACHE_JSON", ".portfoy_yorum_cache.json", False),
)


def _aday_yollar(dosya: str) -> list[str]:
    app_support = os.path.expanduser("~/Library/Application Support/TLYatirimAsistani")
    return [
        os.path.join(ROOT, dosya),
        os.path.join(app_support, "project", dosya),
        os.path.join(app_support, dosya),
    ]


def _bul(dosya: str, explicit: Optional[str] = None) -> Optional[str]:
    if explicit and os.path.isfile(explicit):
        return explicit
    env_key = "VARLIKLARIM_PATH" if dosya == ".varliklarim.json" else ""
    if env_key:
        p = os.getenv(env_key, "").strip()
        if p and os.path.isfile(p):
            return p
    for p in _aday_yollar(dosya):
        if os.path.isfile(p):
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Portföy/cache → GitHub Actions secrets")
    parser.add_argument("--portfoy", help=".varliklarim.json yolu")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPO", "onurrcansever/Makrofinans"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    yuklenen = []
    atlanan = []

    for secret_name, fname, zorunlu in SYNC_DOSYALAR:
        explicit = args.portfoy if fname == ".varliklarim.json" else None
        path = _bul(fname, explicit)
        if not path:
            if zorunlu:
                print(f"[HATA] {fname} bulunamadı.", file=sys.stderr)
                return 1
            atlanan.append(fname)
            continue
        if args.dry_run:
            print(f"[dry-run] {secret_name} ← {path}")
            yuklenen.append(secret_name)
            continue
        try:
            n = dosya_base64_yukle(secret_name, path, repo=args.repo)
            print(f"✓ {secret_name} ← {path} ({n:,} byte)")
            yuklenen.append(secret_name)
        except Exception as exc:
            print(f"[HATA] {secret_name}: {exc}", file=sys.stderr)
            if zorunlu:
                return 1
            atlanan.append(fname)

    if atlanan:
        print(f"  (atlandı: {', '.join(atlanan)})")
    print(f"\n{len(yuklenen)} secret güncellendi. GitHub Actions bir sonraki alarmda kullanır.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
