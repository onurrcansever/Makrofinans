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
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from scripts.github_secrets_util import dosya_base64_yukle, repo_dosya_yukle

# (secret adı, yerel dosya adı, zorunlu)
SYNC_DOSYALAR = (
    ("VARLIKLARIM_JSON", ".varliklarim.json", True),
    ("TEMEL_VERI_CACHE_JSON", ".temel_veri_cache.json", False),
    ("PORTFOY_YORUM_CACHE_JSON", ".portfoy_yorum_cache.json", False),
)

# Private repo dosyası — workflow güncellenmese de checkout'ta portföy gelir
REPO_SYNC_DOSYALAR = (
    (".varliklarim.json", "data/ci_varliklarim.json"),
    (".temel_veri_cache.json", "data/ci_temel_veri_cache.json"),
    (".portfoy_yorum_cache.json", "data/ci_portfoy_yorum_cache.json"),
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
    parser.add_argument("--no-repo-sync", action="store_true", help="data/ci_* repo yüklemesini atla")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT") or ""
    yuklenen = []
    atlanan = []
    repo_yuklenen = []

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

    if not args.no_repo_sync and token.strip():
        print("\nRepo sync (data/ci_*)...")
        for fname, repo_path in REPO_SYNC_DOSYALAR:
            explicit = args.portfoy if fname == ".varliklarim.json" else None
            path = _bul(fname, explicit)
            if not path:
                continue
            if args.dry_run:
                print(f"[dry-run] {repo_path} ← {path}")
                repo_yuklenen.append(repo_path)
                continue
            try:
                sha = repo_dosya_yukle(
                    repo_path,
                    path,
                    message=f"sync: {repo_path} — Mac portföy/cache",
                    repo=args.repo,
                    token=token,
                )
                print(f"✓ {repo_path} ← {path} (commit {sha[:7] if sha else 'ok'})")
                repo_yuklenen.append(repo_path)
            except Exception as exc:
                print(f"[UYARI] {repo_path}: {exc}", file=sys.stderr)

    if atlanan:
        print(f"  (atlandı: {', '.join(atlanan)})")
    print(
        f"\n{len(yuklenen)} secret, {len(repo_yuklenen)} repo dosyası güncellendi. "
        "GitHub Actions bir sonraki alarmda kullanır."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
