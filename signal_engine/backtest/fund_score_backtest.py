# -*- coding: utf-8 -*-
"""Temel skor backtest iskeleti — publish-lag + live-only dışlama.

Tam PIT restatement yoksa sonuçlar indicative_only işaretlenir.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from signal_engine.quality.fund_score import compute_fund_score
from signal_engine.quality.fund_score_pit import (
    LIVE_ONLY_FIELDS,
    METRIC_CLASS,
    available_asof,
    period_visible_at,
)


def statement_usable_at(temel: dict, asof: date) -> bool:
    """Yıllık/çeyrek period_end + lag ile T'de görünür mü?

    period_end yoksa muhafazakâr: usable=False (look-ahead varsayımı yapma).
    """
    pe_q = temel.get("period_end_q")
    pe_y = temel.get("period_end_y")
    if pe_q and period_visible_at(asof, pe_q, annual=False):
        return True
    if pe_y and period_visible_at(asof, pe_y, annual=True):
        return True
    return False


def score_at_asof(
    temel: Optional[dict],
    asof: date,
    peer_ctx: Optional[dict] = None,
) -> Optional[Any]:
    if not temel:
        return None
    if not statement_usable_at(temel, asof):
        return None
    return compute_fund_score(temel, peer_ctx, mode="backtest")


def forward_return(
    prices: List[Tuple[date, float]],
    asof: date,
    horizon_days: int,
) -> Optional[float]:
    """prices: [(date, close), ...] sıralı. asof sonrası horizon getirisi."""
    if not prices:
        return None
    # asof veya sonrası ilk fiyat
    start = None
    for d, p in prices:
        if d >= asof and p and p > 0:
            start = (d, p)
            break
    if start is None:
        return None
    target = start[0] + timedelta(days=horizon_days)
    end = None
    for d, p in prices:
        if d >= target and p and p > 0:
            end = (d, p)
            break
    if end is None:
        return None
    return (end[1] / start[1]) - 1.0


def metric_inventory_table() -> List[Dict[str, str]]:
    rows = []
    for metric, klass in sorted(METRIC_CLASS.items()):
        if klass == "excluded_live_only":
            pit = "excluded_live_only"
        else:
            pit = "publish_lag"
        rows.append({"metric": metric, "class": pit})
    return rows


def summarize_bucket_returns(
    rows: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """rows: {label, ret_3m, ret_6m, ret_12m, tech_azalt}"""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        lab = r.get("label") or "YETERSİZ"
        buckets.setdefault(lab, []).append(r)

    def _avg(xs: List[Optional[float]]) -> Optional[float]:
        vs = [x for x in xs if x is not None]
        if not vs:
            return None
        return sum(vs) / len(vs)

    out: Dict[str, Any] = {}
    for lab, items in buckets.items():
        out[lab] = {
            "n": len(items),
            "ret_3m": _avg([i.get("ret_3m") for i in items]),
            "ret_6m": _avg([i.get("ret_6m") for i in items]),
            "ret_12m": _avg([i.get("ret_12m") for i in items]),
        }

    azalt_saglam = [
        r for r in rows
        if r.get("tech_azalt") and (r.get("label") or "") in ("SAĞLAM", "GÜÇLÜ")
    ]
    azalt_riskli = [
        r for r in rows
        if r.get("tech_azalt") and (r.get("label") or "") in ("ZAYIF", "RİSKLİ")
    ]
    out["_azalt_saglam"] = {
        "n": len(azalt_saglam),
        "ret_3m": _avg([i.get("ret_3m") for i in azalt_saglam]),
        "ret_6m": _avg([i.get("ret_6m") for i in azalt_saglam]),
        "ret_12m": _avg([i.get("ret_12m") for i in azalt_saglam]),
    }
    out["_azalt_riskli"] = {
        "n": len(azalt_riskli),
        "ret_3m": _avg([i.get("ret_3m") for i in azalt_riskli]),
        "ret_6m": _avg([i.get("ret_6m") for i in azalt_riskli]),
        "ret_12m": _avg([i.get("ret_12m") for i in azalt_riskli]),
    }
    return out


def build_validation_payload(
    *,
    n_symbols: int,
    n_pit_symbols: int,
    n_cross_section: int,
    bucket_returns: Optional[Dict[str, Any]] = None,
    look_ahead_clean: bool = True,
    indicative_only: bool = True,
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from signal_engine.quality.fund_score_ui import MIN_CROSS_SECTION, MIN_PIT_SYMBOLS

    sample_adequate = (
        n_pit_symbols >= MIN_PIT_SYMBOLS and n_cross_section >= MIN_CROSS_SECTION
    )
    # Gate: indicative → sample_adequate UI için yetmez
    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "look_ahead_clean": look_ahead_clean,
        "indicative_only": indicative_only,
        "sample_adequate": sample_adequate and not indicative_only,
        "n_symbols": n_symbols,
        "n_pit_symbols": n_pit_symbols,
        "n_cross_section": n_cross_section,
        "min_pit_symbols": MIN_PIT_SYMBOLS,
        "min_cross_section": MIN_CROSS_SECTION,
        "live_only_excluded": sorted(LIVE_ONLY_FIELDS),
        "metric_inventory": metric_inventory_table(),
        "bucket_returns": bucket_returns or {},
        "weights_note": (
            "Ağırlıklar %30/25/25/20 geçmesi optimal değil; "
            "yalnızca 'felaket değil' kapısı."
        ),
        "restatement_warning": (
            "Restatement riski: Finansal kalemler bugünkü Yahoo/finansal tablo "
            "snapshot’ından; o dönemde yayınlanan ilk rakam olmayabilir."
        ),
        "notes": notes or [],
        "publish_lag": {
            "quarter_days": 45,
            "annual_days": 90,
            "available_asof_example": str(
                available_asof(date(2024, 12, 31), annual=True)
            ),
        },
    }
