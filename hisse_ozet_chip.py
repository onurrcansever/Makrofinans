# -*- coding: utf-8 -*-
"""Hisse tablosu Özet sütunu — T (teknik) / A (analist) / H (haber).

Sadece gösterim; AL kararını değiştirmez. Revolut expected-return yok.
"""
from __future__ import annotations

from typing import Any, Optional

_CHIP = (
    "display:inline-block;font-size:11px;font-weight:500;padding:1px 5px;"
    "border-radius:6px;margin-right:3px;line-height:1.25;white-space:nowrap;"
)

_REC_TR = {
    "strong_buy": "Güçlü Al",
    "buy": "Al",
    "hold": "Tut",
    "sell": "Sat",
    "strong_sell": "Sat",
}


def _teknik_etiket(skor: float, regime: str, *, buy_threshold: float) -> str:
    reg = (regime or "").upper()
    if reg == "TRENDING_DOWN" or skor < 42:
        return "Zayıf"
    if skor >= buy_threshold:
        return "Yükseliş"
    return "Nötr"


def _analist_etiket(temel: Optional[dict]) -> str:
    if not temel:
        return "—"
    key = (
        temel.get("recommendationKey")
        or temel.get("analist")
        or ""
    )
    key = str(key).lower().replace(" ", "_")
    return _REC_TR.get(key, "—")


def _haber_etiket(h: Any) -> str:
    notu = (getattr(h, "haber_notu", None) or "").strip()
    return "Var" if notu else "—"


def ozet_parcalar(
    h: Any,
    *,
    temel: Optional[dict] = None,
    buy_threshold: float = 64.0,
) -> tuple[str, str, str]:
    skor = getattr(h, "signal_v2_score", None)
    if skor is None:
        skor = getattr(h, "skor", None) or 0
    try:
        skor_f = float(skor)
    except (TypeError, ValueError):
        skor_f = 0.0
    regime = getattr(h, "signal_v2_regime", "") or ""
    if temel is None:
        try:
            from temel_veri import yukle_cache

            sym = (getattr(h, "sembol", "") or "").strip().upper()
            cache = yukle_cache()
            temel = cache.get(sym) if sym else None
            if temel and temel.get("_bos"):
                temel = None
        except Exception:
            temel = None
    t = _teknik_etiket(skor_f, regime, buy_threshold=buy_threshold)
    a = _analist_etiket(temel)
    haber = _haber_etiket(h)
    return t, a, haber


def ozet_chip_html(
    h: Any,
    *,
    temel: Optional[dict] = None,
    buy_threshold: float = 64.0,
) -> str:
    """Kompakt HTML chip’ler (tablo hücresinde ham HTML)."""
    t, a, haber = ozet_parcalar(h, temel=temel, buy_threshold=buy_threshold)
    colors = {
        "Yükseliş": ("#166534", "#dcfce7"),
        "Nötr": ("#475569", "#f1f5f9"),
        "Zayıf": ("#991b1b", "#fee2e2"),
    }
    tc, tb = colors.get(t, colors["Nötr"])
    parts = [
        f'<span style="{_CHIP}color:{tc};background:{tb};" title="Teknik">T:{t}</span>',
        f'<span style="{_CHIP}color:#334155;background:#f1f5f9;" title="Analist">A:{a}</span>',
        f'<span style="{_CHIP}color:#334155;background:#f1f5f9;" title="Haber">H:{haber}</span>',
    ]
    return "".join(parts)


def ozet_chip_metin(
    h: Any,
    *,
    temel: Optional[dict] = None,
    buy_threshold: float = 64.0,
) -> str:
    """Düz metin (PDF / tooltip)."""
    t, a, haber = ozet_parcalar(h, temel=temel, buy_threshold=buy_threshold)
    return f"T:{t} · A:{a} · H:{haber}"
