# -*- coding: utf-8 -*-
"""Tarama sonrası veri bütünlüğü — özet + aynı borsa bar farkı."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

_log = logging.getLogger(__name__)

BAR_DIFF_WARN = 2  # >2 bar fark → WARN


@dataclass
class VeriOzet:
    islenen: int = 0
    veri_yok: List[str] = field(default_factory=list)
    karantina: List[str] = field(default_factory=list)
    bar_uyarilari: List[str] = field(default_factory=list)

    @property
    def log_satiri(self) -> str:
        vy = ", ".join(self.veri_yok) if self.veri_yok else "—"
        kq = ", ".join(self.karantina) if self.karantina else "—"
        return (
            f"Tarama: {self.islenen} sembol işlendi, "
            f"{len(self.veri_yok)} veri yok: [{vy}], "
            f"{len(self.karantina)} karantina: [{kq}]"
        )

    @property
    def ui_satiri(self) -> Optional[str]:
        parts = []
        if self.veri_yok:
            parts.append(f"{len(self.veri_yok)} sembol veri yok")
        if self.karantina:
            parts.append(f"{len(self.karantina)} karantina")
        if not parts:
            return None
        return "⚠ " + " · ".join(parts)


def _exchange_key(sembol: str, piyasa: str = "") -> str:
    s = (sembol or "").upper()
    if s.endswith(".L") or s.endswith(".LON"):
        return "LSE"
    if s.endswith(".DE"):
        return "XETRA"
    if s.endswith(".IS"):
        return "BIST"
    if s.endswith((".PA", ".AS", ".MI", ".SW")):
        return "EU"
    p = (piyasa or "").upper()
    if p in ("NASDAQ", "SP500"):
        return "US"
    if p == "BIST":
        return "BIST"
    if p == "ETF":
        return "ETF_OTHER"
    return p or "OTHER"


def ozetle_hisseler(hisseler: Sequence) -> VeriOzet:
    """VERI_YOK / karantina listesi — sessiz düşme yok."""
    out = VeriOzet(islenen=len(hisseler))
    for h in hisseler:
        sym = getattr(h, "sembol", "") or ""
        if getattr(h, "sinyal", "") == "VERI_YOK" or getattr(h, "fiyat", None) is None:
            if sym and sym not in out.veri_yok:
                out.veri_yok.append(sym)
        if getattr(h, "veri_quarantine", False):
            if sym and sym not in out.karantina:
                out.karantina.append(sym)
    return out


def bar_sayisi_fark_uyarilari(hisseler: Sequence) -> List[str]:
    """Aynı borsada bar sayısı farkı > BAR_DIFF_WARN → uyarı metinleri."""
    by_ex: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for h in hisseler:
        bd = getattr(h, "close_bar_dates", None)
        if bd is None or len(bd) == 0:
            continue
        if getattr(h, "sinyal", "") == "VERI_YOK":
            continue
        key = _exchange_key(getattr(h, "sembol", ""), getattr(h, "piyasa", ""))
        by_ex[key].append((h.sembol, len(bd)))

    uyarilar: List[str] = []
    for exch, items in sorted(by_ex.items()):
        if len(items) < 2:
            continue
        items_sorted = sorted(items, key=lambda x: x[1])
        lo_sym, lo_n = items_sorted[0]
        hi_sym, hi_n = items_sorted[-1]
        diff = hi_n - lo_n
        if diff > BAR_DIFF_WARN:
            msg = (
                f"{exch}: {lo_sym} {lo_n} bar, {hi_sym} {hi_n} bar — "
                f"{diff} bar fark (Yahoo deliği?)"
            )
            uyarilar.append(msg)
            _log.warning("%s", msg)
    return uyarilar


def tarama_butunluk_ozeti(hisseler: Sequence) -> VeriOzet:
    ozet = ozetle_hisseler(hisseler)
    ozet.bar_uyarilari = bar_sayisi_fark_uyarilari(hisseler)
    _log.info("%s", ozet.log_satiri)
    for u in ozet.bar_uyarilari:
        _log.warning("%s", u)
    print(ozet.log_satiri, flush=True)
    for u in ozet.bar_uyarilari:
        print(f"WARN {u}", flush=True)
    return ozet
