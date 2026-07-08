# -*- coding: utf-8 -*-
"""
BIST (.IS) varlıkları için EUR bazlı 52 hafta bant pozisyonu.

Nominal TL fiyatı enflasyon nedeniyle bandın tepesinde görünür; kur düzeltmesi
değerleme riskini EUR cinsinden ölçer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

import pandas as pd

MIN_52H_GUN = 252
JOIN_UYARI_GUN = 200
DEGERLEME_RISK_ESIK = 70.0


@dataclass
class Bist52hEurSonuc:
    eur_pozisyon_pct: Optional[float] = None
    join_gun: int = 0
    etiket: str = ""  # "" | "yetersiz veri"
    join_uyari: bool = False
    kur_yok: bool = False


def is_bist_sembol(sembol: str) -> bool:
    return str(sembol or "").upper().endswith(".IS")


def _indeks_hizala(seri: pd.Series) -> pd.Series:
    s = seri.dropna().astype(float)
    if s.empty:
        return s
    if isinstance(s.index, pd.DatetimeIndex):
        s = s.copy()
        s.index = s.index.normalize()
    return s


def band_pozisyon_0_100(seri: pd.Series, pencere: int = MIN_52H_GUN) -> Optional[float]:
    """(güncel − min) / (max − min) × 100 — inner seri üzerinde."""
    if len(seri) < pencere:
        return None
    tail = seri.tail(pencere)
    mn = float(tail.min())
    mx = float(tail.max())
    if mx <= mn:
        return None
    cur = float(tail.iloc[-1])
    return (cur - mn) / (mx - mn) * 100.0


def bist_52h_eur_hesapla(
    tl_close: pd.Series,
    eurtry_close: pd.Series,
    min_gun: int = MIN_52H_GUN,
) -> Bist52hEurSonuc:
    """
    TL kapanış ile EURTRY inner-join (ffill yok); son min_gun günlük EUR fiyat bandı.
    """
    tl = _indeks_hizala(tl_close)
    kur = _indeks_hizala(eurtry_close)

    if tl.empty or kur.empty:
        return Bist52hEurSonuc(kur_yok=True)

    ortak = tl.index.intersection(kur.index)
    if len(ortak) == 0:
        return Bist52hEurSonuc(kur_yok=True)

    df = pd.DataFrame({"tl": tl.loc[ortak], "eurtry": kur.loc[ortak]}).dropna()
    join_gun = len(df)

    if join_gun < min_gun:
        return Bist52hEurSonuc(
            join_gun=join_gun,
            etiket="yetersiz veri",
            join_uyari=join_gun < JOIN_UYARI_GUN,
        )

    eur_fiyat = df["tl"] / df["eurtry"]
    poz = band_pozisyon_0_100(eur_fiyat, pencere=min_gun)
    return Bist52hEurSonuc(
        eur_pozisyon_pct=round(poz, 1) if poz is not None else None,
        join_gun=join_gun,
        join_uyari=join_gun < JOIN_UYARI_GUN,
    )


def degerleme_52h_pozisyon(h) -> Optional[float]:
    """
    Değerleme skoru / risk uyarısı girdisi.
    BIST: EUR band (yetersiz/kur yok → None, nominal kullanılmaz).
    Diğer: mevcut TL/nominal zirve_52h_pct.
    """
    if is_bist_sembol(getattr(h, "sembol", "")):
        if getattr(h, "zirve_52h_eur_etiket", "") == "yetersiz veri":
            return None
        if getattr(h, "zirve_52h_eur_pct", None) is not None:
            return h.zirve_52h_eur_pct
        return None
    return getattr(h, "zirve_52h_pct", None)


def format_52h_metin(h) -> str:
    """Rapor/tablo: '52H %97 (TL) · %71 (EUR)' veya tek nominal."""
    tl = getattr(h, "zirve_52h_pct", None)
    tl_txt = f"{tl:.0f}" if tl is not None else "—"
    if not is_bist_sembol(getattr(h, "sembol", "")):
        return f"52H %{tl_txt}"
    etiket = getattr(h, "zirve_52h_eur_etiket", "") or ""
    eur = getattr(h, "zirve_52h_eur_pct", None)
    if etiket == "yetersiz veri":
        return f"52H %{tl_txt} (TL) · yetersiz veri (EUR)"
    if eur is not None:
        return f"52H %{tl_txt} (TL) · %{eur:.0f} (EUR)"
    return f"52H %{tl_txt} (TL) · — (EUR)"


def bist_52h_eur_uygula(h, tl_close: pd.Series, eurtry_close: Optional[pd.Series]) -> None:
    """HisseAnaliz alanlarını doldurur (.IS dışında no-op)."""
    if not is_bist_sembol(getattr(h, "sembol", "")):
        return
    if eurtry_close is None or eurtry_close.empty:
        h.zirve_52h_eur_pct = None
        h.zirve_52h_eur_etiket = ""
        h.bist_52h_join_gun = None
        h.bist_52h_join_uyari = False
        h.bist_52h_kur_yok = True
        return
    sonuc = bist_52h_eur_hesapla(tl_close, eurtry_close)
    h.zirve_52h_eur_pct = sonuc.eur_pozisyon_pct
    h.zirve_52h_eur_etiket = sonuc.etiket
    h.bist_52h_join_gun = sonuc.join_gun
    h.bist_52h_join_uyari = sonuc.join_uyari
    h.bist_52h_kur_yok = sonuc.kur_yok
