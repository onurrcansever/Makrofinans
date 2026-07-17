# -*- coding: utf-8 -*-
"""
Hisse Faktör / Peer Katmanı
============================
Sektör içi momentum sıralaması ve endeks karşılaştırması.
RSI/SMA tek başına yeterli değil — göreceli güç ekler.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import pandas as pd

from stock_scanner import _close_al, _degisim

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

ENDEKS_SEMBOL = {
    "BIST": "XU100.IS",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
}

ENDEKS_CACHE: Dict[str, Optional[float]] = {}


def _endeks_momentum(df: pd.DataFrame, piyasa: str, gun: int = 63) -> Optional[float]:
    sym = ENDEKS_SEMBOL.get(piyasa)
    if not sym:
        return None
    if sym not in ENDEKS_CACHE:
        close = _close_al(df, sym)
        ENDEKS_CACHE[sym] = _degisim(close, gun) if not close.empty else None
    return ENDEKS_CACHE.get(sym)


def _yuzdelik_sira(degerler: List[Tuple[str, float]]) -> Dict[str, float]:
    if len(degerler) < 2:
        return {k: 50.0 for k, _ in degerler}
    sirali = sorted(degerler, key=lambda x: x[1])
    n = len(sirali)
    return {k: (i / (n - 1)) * 100 for i, (k, _) in enumerate(sirali)}


def faktor_katmani_uygula(hisseler: List["HisseAnaliz"], df: pd.DataFrame) -> None:
    global ENDEKS_CACHE
    ENDEKS_CACHE = {}

    gruplar: Dict[Tuple[str, str], list] = {}
    for h in hisseler:
        if h.piyasa in ("ETF", "EMTIA") or h.fiyat is None:
            continue
        key = (h.piyasa, h.sektor or "genel")
        gruplar.setdefault(key, []).append(h)

    for piyasa, _sektor in gruplar:
        _endeks_momentum(df, piyasa)

    for (_piyasa, _sektor), grup in gruplar.items():
        mom_list = []
        for h in grup:
            m = h.degisim_3ay if h.degisim_3ay is not None else h.degisim_1ay
            if m is not None:
                mom_list.append((h.sembol, m))
        yuzdelik = _yuzdelik_sira(mom_list) if mom_list else {}
        idx_mom = _endeks_momentum(df, _piyasa)

        for h in grup:
            notlar = []
            m = h.degisim_3ay if h.degisim_3ay is not None else h.degisim_1ay
            peer_pct = yuzdelik.get(h.sembol, 50.0)
            h.peer_yuzdelik = round(peer_pct, 0)

            if m is not None and idx_mom is not None:
                rel = m - idx_mom
                h.endeks_gore = round(rel, 1)
                if rel >= 5:
                    notlar.append(f"Endekse göre güçlü (+{rel:.0f} pp 3A)")
                elif rel <= -5:
                    notlar.append(f"Endekse göre zayıf ({rel:.0f} pp 3A)")

            if len(grup) >= 3:
                if peer_pct >= 75:
                    notlar.append(f"Sektör içi üst çeyrek (peer %{peer_pct:.0f})")
                elif peer_pct <= 25:
                    notlar.append(f"Sektör içi alt çeyrek (peer %{peer_pct:.0f})")

            h.faktor_notu = " · ".join(notlar) if notlar else "Faktör nötr"

            delta = 0.0
            if peer_pct >= 75 and (h.endeks_gore or 0) >= 0:
                delta += 5
            elif peer_pct <= 25 and (h.endeks_gore or 0) <= -3:
                delta -= 5
            elif (h.endeks_gore or 0) >= 8:
                delta += 3
            elif (h.endeks_gore or 0) <= -8:
                delta -= 4

            if delta:
                h.skor = max(0, min(100, h.skor + delta))
                if delta > 0 and h.faktor_notu != "Faktör nötr":
                    h.faktor_notu += f" · skor +{delta:.0f}"
                elif delta < 0:
                    h.faktor_notu += f" · skor {delta:.0f}"
