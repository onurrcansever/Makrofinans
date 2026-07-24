#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kısa mom canlı izleme — haftalık çalıştır; rollback önerisi basar.

Proxy: tarama/cache yoksa yfinance ile küçük evrende REDUCE↔WATCH flip oranı.
Tam canlı tarama entegrasyonu sonra eklenebilir; şimdilik ops checklist + eşik kontrolü.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.backtest.trend_short_mom_backtest import (  # noqa: E402
    REPORT_DIR,
    download_closes,
    walk_symbol,
)
from signal_engine.config.loader import load_signal_config  # noqa: E402

# Küçük izleme evreni (hızlı)
MONITOR_SYMBOLS = ["AAPL", "MSFT", "ADBE", "INTU", "NVDA", "JPM", "XOM", "KO"]


def main() -> int:
    cfg = load_signal_config()
    sm = cfg.short_momentum or {}
    mon = sm.get("monitor") or {}
    ref_rate = float(mon.get("backtest_ref_whipsaw_rate") or 0.001064)
    mult = float(mon.get("rollback_whipsaw_mult") or 2.0)
    enabled = bool(sm.get("enabled"))
    preset = sm.get("preset") or "siki"

    print(f"enabled={enabled} preset={preset}")
    print(f"rollback if live_whipsaw_rate > {ref_rate * mult:.6f} "
          f"(ref={ref_rate} × {mult})")

    closes, bench = download_closes(MONITOR_SYMBOLS, period="2y")
    flips = 0
    steps = 0
    for sym, close in closes.items():
        if len(close) < 300:
            continue
        w = walk_symbol(close, bench, cfg, step=5, symbol=sym)
        arm = preset if preset in w else "siki"
        data = w.get(arm) or w["base"]
        flips += int(data.get("flips") or 0)
        steps += max(0, len(data.get("levels") or []) - 1)

    rate = flips / steps if steps else 0.0
    limit = ref_rate * mult
    suggest_rollback = enabled and rate > limit

    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "enabled": enabled,
        "preset": preset,
        "flips": flips,
        "steps": steps,
        "whipsaw_rate": rate,
        "limit": limit,
        "suggest_rollback": suggest_rollback,
        "criterion": (
            f"İlk/her izlemede whipsaw_rate > backtest_ref×{mult} → enabled:false"
        ),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "trend_short_mom_monitor_latest.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(snap, ensure_ascii=False, indent=2))
    if suggest_rollback:
        print("⚠ ÖNERİ: ROLLBACK — signal_config.yaml → short_momentum.enabled: false")
        return 2
    print("OK: rollback eşiği aşılmadı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
