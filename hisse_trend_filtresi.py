# -*- coding: utf-8 -*-
"""
Hisse trend filtresi — RSI dipte olsa bile düşen trendde "Trend alımı" engellenir.
SMA200, 52 hafta zirvesi yakınlığı, 1 ay momentum.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz


def _sma(seri: pd.Series, n: int) -> Optional[float]:
    if len(seri) < n:
        return None
    v = seri.rolling(n).mean().iloc[-1]
    return float(v) if pd.notna(v) else None


def trend_filtresi_uygula(h: "HisseAnaliz", close: pd.Series) -> None:
    if close.empty or h.fiyat is None:
        h.trend_notu = "Trend verisi yok"
        return

    sma200 = _sma(close, 200)
    pencere = min(252, len(close))
    high_52 = float(close.tail(pencere).max()) if pencere >= 20 else None
    zirve_pct = (h.fiyat / high_52 * 100) if high_52 and high_52 > 0 else None

    h.sma200 = sma200
    h.zirve_52h_pct = round(zirve_pct, 1) if zirve_pct is not None else None

    notlar = []
    engelle = False

    ay1 = h.degisim_1ay
    if ay1 is not None and ay1 < -3.0:
        notlar.append(f"1 ay düşüş {ay1:+.1f}%")
        if h.sinyal == "TREND_ALIM":
            engelle = True

    if sma200 is not None and h.fiyat < sma200:
        notlar.append("SMA200 altı")
        if h.sinyal in ("TREND_ALIM",):
            engelle = True
        elif h.sinyal == "ALIM_FIRSATI" and ay1 is not None and ay1 < -6.0:
            engelle = True

    if zirve_pct is not None and zirve_pct < 75:
        notlar.append(f"52H zirve %{zirve_pct:.0f}")

    if engelle:
        eski = h.sinyal
        h.sinyal = "BEKLE"
        h.skor = max(0, h.skor - 12)
        h.gerekce += (
            f"; Trend filtresi: {eski} kaldırıldı "
            f"({' · '.join(notlar)})"
        )
        h.trend_notu = "Trend filtresi: BEKLE — " + " · ".join(notlar)
    elif notlar:
        h.trend_notu = "Uyarı: " + " · ".join(notlar)
    else:
        sma200_txt = f"SMA200 üstü" if sma200 and h.fiyat >= sma200 else "SMA200 —"
        z_txt = f"52H %{zirve_pct:.0f}" if zirve_pct else ""
        h.trend_notu = " · ".join(x for x in (sma200_txt, z_txt) if x) or "Trend filtresi OK"
