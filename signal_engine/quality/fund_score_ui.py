# -*- coding: utf-8 -*-
"""FUND_SCORE_UI gate — FAZ5 validation + geliştirme FORCE bayrağı."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Örneklem eşiği (raporda sabitlenir)
MIN_PIT_SYMBOLS = 30
MIN_CROSS_SECTION = 4

_DEFAULT_REPORT = (
    Path(__file__).resolve().parents[1] / "reports" / "fund_score_validation.json"
)

EXPERIMENTAL_BANNER = (
    "Temel skor — deneysel, sınırlı geriye dönük doğrulama "
    "(PIT arşivi yok; restatement riski). Teknik kararı değiştirmez."
)


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _force_on() -> bool:
    try:
        from config import FUND_SCORE_UI_FORCE

        return bool(FUND_SCORE_UI_FORCE)
    except Exception:
        return _env_truthy("FUND_SCORE_UI_FORCE", "0")


def _ui_want() -> bool:
    try:
        from config import FUND_SCORE_UI

        return bool(FUND_SCORE_UI)
    except Exception:
        return _env_truthy("FUND_SCORE_UI", "0")


def validation_report_path() -> Path:
    env = os.getenv("FUND_SCORE_VALIDATION_JSON", "").strip()
    return Path(env) if env else _DEFAULT_REPORT


def load_validation_summary(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = path or validation_report_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def fund_score_is_experimental() -> bool:
    """FORCE ile açık = prod gate geçmeden deneysel gösterim."""
    return _force_on() and not fund_score_prod_gate_ok()[0]


def fund_score_prod_gate_ok(
    summary: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """FAZ5 validation — FORCE yok sayılır; gerçek prod kapısı."""
    data = summary if summary is not None else load_validation_summary()
    if not data:
        return False, "validation raporu yok"
    if data.get("look_ahead_clean") is not True:
        return False, "look_ahead_clean != true"
    if data.get("indicative_only") is True:
        return False, "indicative_only (PIT yetersiz)"
    if data.get("sample_adequate") is not True:
        return False, "örneklem yetersiz"
    n_pit = int(data.get("n_pit_symbols") or 0)
    n_cs = int(data.get("n_cross_section") or 0)
    if n_pit < MIN_PIT_SYMBOLS or n_cs < MIN_CROSS_SECTION:
        return False, f"örneklem eşiği (pit={n_pit}, cs={n_cs})"
    return True, "gate OK"


def fund_score_ui_allowed(
    summary: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    UI gösterilebilir mi?
    - FUND_SCORE_UI_FORCE=1 → geliştirme (banner ile)
    - FUND_SCORE_UI=1 + FAZ5 gate → prod
    """
    if _force_on():
        return True, "FUND_SCORE_UI_FORCE=1 (geliştirme / deneysel)"

    ok, reason = fund_score_prod_gate_ok(summary)
    if not ok:
        return False, reason

    if not _ui_want():
        return False, "FUND_SCORE_UI env kapalı (gate geçti ama flag yok)"

    return True, "gate OK + FUND_SCORE_UI=1"


def fund_score_ui_enabled() -> bool:
    ok, _ = fund_score_ui_allowed()
    return ok


def fund_score_banner_text() -> Optional[str]:
    """Deneysel uyarı metni; prod gate temizse None."""
    if not fund_score_ui_enabled():
        return None
    if fund_score_is_experimental() or _force_on():
        # FORCE açıkken her zaman banner (prod gate geçse bile FORCE bilinçli debug)
        return EXPERIMENTAL_BANNER
    return None
