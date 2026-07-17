# -*- coding: utf-8 -*-
"""Hisse/ETF/emtia AL adayları — WhatsApp özet ve sinyal alarmları için ortak format."""
from __future__ import annotations

from typing import List, Tuple

import config


def _etf_mi(h) -> bool:
    return getattr(h, "piyasa", "") == "ETF" or getattr(h, "varlik_turu", "") == "etf"


def _emtia_mi(h) -> bool:
    return getattr(h, "piyasa", "") == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia"


def _kisalt(h) -> str:
    sym = h.sembol or h.ad or "?"
    return sym.replace(".IS", "").split(".")[0][:12]


def al_adaylari(hisseler: list) -> List:
    """Sistem kriterine göre AL (UYGUN) adayları — fiyatı olanlar."""
    return [
        h for h in hisseler
        if getattr(h, "alim_uygun", "") == "UYGUN" and h.fiyat is not None
    ]


def al_etiket_kisa(h) -> str:
    """Kompakt: CSPX GÜÇLÜ AL 84(%92) · emtia: Altın (ons) AL — $3.985, skor 67"""
    skor = round(h.skor or 0)
    karar = getattr(h, "signal_v2_decision", "") or "AL"
    if _emtia_mi(h):
        ad = (h.ad or _kisalt(h))[:24]
        fiyat = h.fiyat
        if fiyat is not None:
            return f"{ad} {karar} — ${fiyat:,.3f}, skor {skor}"
        return f"{ad} {karar}, skor {skor}"
    sym = _kisalt(h)
    pct = getattr(h, "signal_v2_percentile", None)
    if pct is not None:
        return f"{sym} {karar} {skor}(%{pct:.0f})"
    return f"{sym} {karar} {skor}"


def emtia_sinyal_satiri(h) -> str:
    """🔼 Altın (ons) AL sinyali — $3.985, skor 67"""
    from temel_veri import sinyal_isaret_hisse

    ok = sinyal_isaret_hisse(h)
    ad = (h.ad or _kisalt(h))[:24]
    karar = getattr(h, "signal_v2_decision", "") or "AL"
    skor = round(getattr(h, "signal_v2_score", None) or h.skor or 0)
    if h.fiyat is not None:
        return f"{ok} {ad} {karar} sinyali — ${h.fiyat:,.3f}, skor {skor}"
    return f"{ok} {ad} {karar} sinyali — skor {skor}"


def _limit(items: list, cap: int) -> list:
    if cap and cap > 0:
        return items[:cap]
    return items


def guncel_al_satirlar(hisseler: list) -> List[str]:
    """
    Tüm AL adayları — hisse / ETF / emtia ayrı, skor sıralı.
    OZET_AL_MAX_HISSE / OZET_AL_MAX_ETF = 0 → sınırsız (varsayılan).
    """
    uygun = al_adaylari(hisseler)
    if not uygun:
        return [" AL aday yok"]

    al_h = sorted(
        [h for h in uygun if not _etf_mi(h) and not _emtia_mi(h)],
        key=lambda x: -(x.skor or 0),
    )
    al_e = sorted([h for h in uygun if _etf_mi(h)], key=lambda x: -(x.skor or 0))
    al_m = sorted([h for h in uygun if _emtia_mi(h)], key=lambda x: -(x.skor or 0))
    cap_h = config.OZET_AL_MAX_HISSE
    cap_e = config.OZET_AL_MAX_ETF
    shown_h = _limit(al_h, cap_h)
    shown_e = _limit(al_e, cap_e)

    satirlar: List[str] = [
        f" Toplam {len(uygun)} AL ({len(al_h)} hisse · {len(al_e)} ETF · {len(al_m)} emtia)",
    ]
    if al_h:
        etiketler = ", ".join(al_etiket_kisa(h) for h in shown_h)
        ek = f" +{len(al_h) - len(shown_h)} gizli" if len(shown_h) < len(al_h) else ""
        satirlar.append(f" Hisse ({len(shown_h)}): {etiketler}{ek}")
    if al_e:
        etiketler = ", ".join(al_etiket_kisa(h) for h in shown_e)
        ek = f" +{len(al_e) - len(shown_e)} gizli" if len(shown_e) < len(al_e) else ""
        satirlar.append(f" ETF ({len(shown_e)}): {etiketler}{ek}")
    if al_m:
        etiketler = ", ".join(al_etiket_kisa(h) for h in al_m)
        satirlar.append(f" Emtia ({len(al_m)}): {etiketler}")
    return satirlar


def degisim_al_etiket(h) -> str:
    """Değişim satırı için kısa etiket."""
    if _emtia_mi(h):
        return emtia_sinyal_satiri(h)
    return al_etiket_kisa(h)
