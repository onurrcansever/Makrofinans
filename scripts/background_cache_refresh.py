#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mac LaunchAgent / CLI — sessiz fiyat + tarama + analist önbellek yenileme.

Kullanım:
  python scripts/background_cache_refresh.py
  python main.py --cache-yenile
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _log_path() -> Path:
    app_support = Path.home() / "Library" / "Application Support" / "TLYatirimAsistani"
    if app_support.is_dir():
        return app_support / "cache_refresh.log"
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "cache_refresh.log"


def main() -> int:
    log_file = _log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    log("=== background_cache_refresh start ===")
    from background_cache import run_background_refresh

    out = run_background_refresh(
        quotes=True,
        tarama=True,
        analist=True,
        max_workers=3,
        log=log,
    )
    log(f"=== done ok={out.get('ok')} elapsed={out.get('elapsed_sec', 0):.1f}s ===")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
