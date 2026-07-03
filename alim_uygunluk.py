# -*- coding: utf-8 -*-
"""
Alım uygunluk etiketi — bileşik skor (teknik + temel) ve vade uyumu.
Finansal tavsiye değil; teknik + temel + profil birleşimi.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Set, Tuple

import config

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

ALIM_UYGUN_ETIKET = {
    "UYGUN": "🟢 Alım için uygun",
    "SINIRLI": "🟡 Dikkatli — sınırlı uygun",
    "UYGUN_DEGIL": "🔴 Alım için uygun değil",
    "IZLE": "⚪ İzle / bekle",
}

ALIM_AKSIYON_TABLO = {
    "UYGUN": "AL",
    "SINIRLI": "DİKKAT",
    "UYGUN_DEGIL": "ALMA",
    "IZLE": "BEKLE",
}


def alim_aksiyon_kisa(kod: str) -> str:
    return ALIM_AKSIYON_TABLO.get(kod, "BEKLE")


def alim_aksiyon_hucre(h: "HisseAnaliz") -> str:
    return alim_aksiyon_kisa(getattr(h, "alim_uygun", "IZLE"))


def _bilesik(h: "HisseAnaliz") -> float:
    return float(getattr(h, "bilesik_skor", None) or h.skor or 0)


def _degerlendir(
    h: "HisseAnaliz",
    aday_semboller: Set[str],
    esik: float,
    profil: Optional[object] = None,
) -> Tuple[str, str, str]:
    from investor_profile import YatirimProfili
    from temel_skor import bilesik_etiket_kodu

    profil = profil or YatirimProfili()
    bilesik = _bilesik(h)
    aday = h.sembol in aday_semboller
    trend = h.trend_notu or ""

    if h.fiyat is None or h.sinyal == "VERI_YOK":
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], "Fiyat/veri yok"

    if h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], "Aşırı alım veya yüksek risk"

    vade_uygun = getattr(h, "vade_uygun", True)
    if not vade_uygun:
        return (
            "IZLE",
            ALIM_UYGUN_ETIKET["IZLE"],
            "Vade uyumsuz — bu profil için önerilmez",
        )

    kod = bilesik_etiket_kodu(bilesik, vade_uygun=True)

    if kod == "UYGUN_DEGIL":
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], f"Bileşik skor düşük ({bilesik:.0f})"

    trend_engellendi = h.sinyal == "BEKLE" and (
        "Trend filtresi: BEKLE" in trend or "Trend filtresi:" in (h.gerekce or "")
    )
    if trend_engellendi and kod == "UYGUN":
        kod = "SINIRLI"

    if h.sinyal == "BEKLE" and kod in ("UYGUN", "SINIRLI"):
        if bilesik < config.BILESKE_AL_ESIK + 5:
            kod = "IZLE" if kod == "SINIRLI" else "SINIRLI"

    sert: List[str] = []
    yumusak: List[str] = []

    if getattr(h, "temel_not", ""):
        yumusak.append(h.temel_not.replace("Temel skor düşük: ", "")[:55])

    if not aday and kod == "UYGUN":
        yumusak.append("Ana aday listesinde değil")

    if trend.startswith("Uyarı:"):
        yumusak.append(trend.replace("Uyarı:", "").strip()[:40])

    if h.haber_notu and any(x in h.haber_notu.lower() for x in ("olumsuz", "düşür", "bekle")):
        sert.append("Haber baskısı")

    if sert and kod == "UYGUN":
        kod = "SINIRLI"

    if kod == "UYGUN":
        notu = f"Bileşik {bilesik:.0f} (T:{getattr(h, 'teknik_skor', 0):.0f} F:{getattr(h, 'temel_skor', 0):.0f})"
        if aday:
            notu += " — aday listesinde"
        return "UYGUN", ALIM_UYGUN_ETIKET["UYGUN"], notu

    if kod == "SINIRLI":
        notu = "; ".join((sert + yumusak)[:2]) or f"Bileşik {bilesik:.0f} — dikkatli"
        return "SINIRLI", ALIM_UYGUN_ETIKET["SINIRLI"], notu

    if kod == "IZLE":
        notu = "; ".join(yumusak[:2]) if yumusak else f"Bileşik {bilesik:.0f} — izle"
        return "IZLE", ALIM_UYGUN_ETIKET["IZLE"], notu

    return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], f"Bileşik {bilesik:.0f}"


def alim_uygunluk_uygula(
    hisseler: List["HisseAnaliz"],
    aday_semboller: Set[str],
    esik: float,
    profil: Optional[object] = None,
) -> None:
    for h in hisseler:
        kod, etiket, notu = _degerlendir(h, aday_semboller, esik, profil=profil)
        h.alim_uygun = kod
        h.alim_uygun_etiket = etiket
        h.alim_uygun_not = notu
