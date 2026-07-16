# -*- coding: utf-8 -*-
"""Karar geçmişi — sembol bazlı histerezis state."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Dict, Optional, Tuple

from etf_universe import REVOLUT_ETFLER
from signal_engine.decisions.state_machine import LEVEL_LABELS

STATE_PATH = os.getenv("DECISION_HISTORY_PATH", ".decision_history.json")
DEFAULT_TTL_DAYS = int(os.getenv("DECISION_HISTORY_TTL_DAYS", "30"))

_REVOLUT_TICKER_TO_YAHOO = {t[4].upper(): t[0] for t in REVOLUT_ETFLER}
_YAHOO_CANONICAL = {t[0].upper(): t[0] for t in REVOLUT_ETFLER}


class DecisionHistoryError(RuntimeError):
    """Bozuk/parse edilemeyen karar geçmişi dosyası."""


def canonical_decision_symbol(sembol: str) -> str:
    """Tek kanonik form — ETF ticker (EQQQ) → Yahoo (EQQQ.L)."""
    s = (sembol or "").strip().upper()
    if not s:
        return s
    if s in _YAHOO_CANONICAL:
        return _YAHOO_CANONICAL[s]
    if s in _REVOLUT_TICKER_TO_YAHOO:
        return _REVOLUT_TICKER_TO_YAHOO[s]
    return s


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _days_between(later: date, earlier: date) -> int:
    return (later - earlier).days


def _load() -> Dict[str, dict]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise DecisionHistoryError(f"Karar geçmişi bozuk: {STATE_PATH}") from exc
    if not isinstance(data, dict):
        raise DecisionHistoryError(f"Karar geçmişi beklenmeyen format: {STATE_PATH}")
    return data


def _save(data: Dict[str, dict]) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".decision_history.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def get_prev_decision(
    sembol: str,
    *,
    asof: Optional[str] = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> Tuple[str, bool, str]:
    """
    Önceki karar kodu. Dönüş: (code, cold_start, reason).
    TTL bar/veri tarihine göre — asof yoksa cold start (now() kullanılmaz).
    """
    key = canonical_decision_symbol(sembol)
    if not key:
        return "", True, "cold start: sembol yok"

    if not asof:
        return "", True, "cold start: bar tarihi yok"

    data = _load()
    rec = data.get(key)
    if not rec:
        return "", True, "cold start: önceki karar yok"

    code = str(rec.get("code") or "")
    if not code:
        return "", True, "cold start: önceki karar yok"

    rec_date = rec.get("tarih") or rec.get("date") or ""
    if not rec_date:
        return "", True, "cold start: kayıt tarihi yok"

    try:
        saved = _parse_date(rec_date)
        ref = _parse_date(asof)
    except ValueError:
        return "", True, "cold start: kayıt tarihi geçersiz"

    age = _days_between(ref, saved)
    if age > ttl_days:
        return "", True, f"cold start: son karar {age} gün önce (TTL {ttl_days})"

    return code, False, ""


def update_decision_history(
    sembol: str,
    code: str,
    score: float,
    *,
    asof: str,
) -> None:
    """Tarama sonrası karar kaydı — asof (bar tarihi) zorunlu."""
    key = canonical_decision_symbol(sembol)
    if not key or not code or not asof:
        return
    data = _load()
    data[key] = {
        "code": code,
        "karar": LEVEL_LABELS.get(code, code),
        "skor": round(float(score), 1),
        "tarih": asof,
    }
    _save(data)


def clear_decision_history() -> None:
    """Test / cold-start yardımcısı."""
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
