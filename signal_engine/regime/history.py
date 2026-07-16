# -*- coding: utf-8
"""Rejim geçmişi — günlük rejim süresi."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Optional, Tuple

STATE_PATH = os.getenv("REGIME_HISTORY_PATH", ".regime_history.json")


def _load() -> Dict[str, dict]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: Dict[str, dict]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_regime_history(sembol: str, regime: str) -> Tuple[int, bool]:
    """
    Günlük rejim kaydı. Dönüş: (aynı rejimde gün sayısı, son 3 günde değişti mi).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load()
    rec = data.get(sembol, {"regime": regime, "since": today, "days": 1, "last_change": today})
    fresh = False
    if rec.get("regime") != regime:
        rec = {"regime": regime, "since": today, "days": 1, "last_change": today}
        fresh = True
    else:
        if rec.get("since") != today:
            rec["days"] = int(rec.get("days", 1)) + 1
    data[sembol] = rec
    _save(data)
    days = int(rec.get("days", 1))
    try:
        changed = datetime.strptime(rec.get("last_change", today), "%Y-%m-%d")
        fresh_change = (datetime.now() - changed).days <= 3
    except ValueError:
        fresh_change = fresh
    return days, fresh_change or fresh
