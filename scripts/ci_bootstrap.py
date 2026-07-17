#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions — secret restore + repo sync dosyalarını hazırla."""
from __future__ import annotations

import base64
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (env secret adı, hedef dosya)
_SECRET_RESTORE = (
    ("VARLIKLARIM_JSON", ".varliklarim.json"),
    ("TEMEL_VERI_CACHE_JSON", ".temel_veri_cache.json"),
    ("PORTFOY_YORUM_CACHE_JSON", ".portfoy_yorum_cache.json"),
)

# checkout'taki sync dosyası → yerel gizli dosya (yalnızca hedef yoksa)
_REPO_COPY = (
    ("data/ci_varliklarim.json", ".varliklarim.json"),
    ("data/ci_temel_veri_cache.json", ".temel_veri_cache.json"),
    ("data/ci_portfoy_yorum_cache.json", ".portfoy_yorum_cache.json"),
)


def _restore_secret(env_name: str, dest: str) -> bool:
    val = os.getenv(env_name, "").strip()
    if not val:
        return False
    path = os.path.join(ROOT, dest)
    try:
        raw = base64.b64decode(val)
    except Exception:
        return False
    if not raw.strip():
        return False
    with open(path, "wb") as f:
        f.write(raw)
    print(f"ci_bootstrap: {env_name} → {dest} ({len(raw):,} byte)")
    return True


def ci_bootstrap() -> None:
    if not os.getenv("GITHUB_ACTIONS"):
        return

    restored = False
    for env_name, dest in _SECRET_RESTORE:
        if _restore_secret(env_name, dest):
            restored = True

    if not restored:
        script = os.path.join(ROOT, "scripts", "github_ci_restore.sh")
        if os.path.isfile(script) and any(os.getenv(k) for k, _ in _SECRET_RESTORE):
            subprocess.run(["bash", script], cwd=ROOT, check=False)

    for src, dest in _REPO_COPY:
        dest_path = os.path.join(ROOT, dest)
        src_path = os.path.join(ROOT, src)
        if os.path.isfile(dest_path) or not os.path.isfile(src_path):
            continue
        with open(src_path, "rb") as sf, open(dest_path, "wb") as df:
            df.write(sf.read())
        print(f"ci_bootstrap: {src} → {dest}")


if __name__ == "__main__":
    ci_bootstrap()
    raise SystemExit(0)
