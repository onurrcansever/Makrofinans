# -*- coding: utf-8 -*-
"""
Alım uygunluk etiketi — bileşik skor + trend/momentum hikâye filtresi.
Tek hisse AL yalnızca teknik teyit + sağlıklı trend + makul değerlemede verilir.
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


def _tek_hisse_mi(h: "HisseAnaliz") -> bool:
    return h.piyasa != "ETF" and getattr(h, "varlik_turu", "hisse") != "etf"


def _hikaye_al_kontrol(h: "HisseAnaliz") -> Tuple[bool, List[str]]:
    """
    Tek hisse AL (UYGUN) için zorunlu hikâye kontrolleri.
    Dönüş: (geçti_mi, engel_nedenleri)
    """
    if not _tek_hisse_mi(h):
        return True, []

    engeller: List[str] = []

    if h.sinyal not in ("ALIM_FIRSATI", "TREND_ALIM"):
        engeller.append("teknik teyit yok (AL/TREND sinyali gerekli)")

    zirve = getattr(h, "zirve_52h_pct", None)
    if zirve is not None and zirve >= config.AL_TEK_HISSE_ZIRVE_52H_MAX:
        engeller.append(f"52H zirveye yakın (%{zirve:.0f})")

    sma200 = getattr(h, "sma200", None)
    dip_alim = h.sinyal == "ALIM_FIRSATI" and zirve is not None and zirve < 65
    if (
        config.AL_TEK_HISSE_SMA200_ZORUNLU
        and not dip_alim
        and sma200 is not None
        and h.fiyat is not None
        and h.fiyat < sma200
    ):
        engeller.append("SMA200 altı — ana trend zayıf")

    ay1 = h.degisim_1ay
    if ay1 is not None and ay1 < config.AL_TEK_HISSE_AY1_MIN:
        engeller.append(f"1 ay momentum zayıf ({ay1:+.1f}%)")

    ay3 = h.degisim_3ay
    if (
        ay3 is not None
        and ay3 < config.AL_TEK_HISSE_AY3_MIN
        and h.sinyal != "ALIM_FIRSATI"
    ):
        engeller.append(f"3 ay momentum negatif ({ay3:+.1f}%)")

    endeks = getattr(h, "endeks_gore", None)
    if endeks is not None and endeks < config.AL_TEK_HISSE_ENDEKS_MIN:
        engeller.append(f"endekse göre zayıf ({endeks:+.0f} pp)")

    y1 = getattr(h, "degisim_1y", None)
    if y1 is not None and y1 < config.AL_TEK_HISSE_Y1_MIN:
        engeller.append(f"1 yıl getirisi zayıf ({y1:+.1f}%)")

    return len(engeller) == 0, engeller


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

    # 1 yıl getirisi çok zayıfsa AL/DİKKAT verme (enflasyon altı hikâye)
    if _tek_hisse_mi(h):
        y1 = getattr(h, "degisim_1y", None)
        if y1 is not None and y1 < config.AL_TEK_HISSE_Y1_IZLE:
            kod = "IZLE"
            sert.append(f"1 yıl TL getirisi yetersiz ({y1:+.1f}%)")
        elif y1 is not None and y1 < config.AL_TEK_HISSE_Y1_MIN and kod in ("UYGUN", "SINIRLI"):
            kod = "IZLE" if kod == "SINIRLI" else "SINIRLI"
            yumusak.append(f"1 yıl getirisi sınırlı ({y1:+.1f}%)")

    # Tek hisse AL — trend/momentum hikâye filtresi (portföy + tablo)
    if kod == "UYGUN" and _tek_hisse_mi(h):
        gecti, engeller = _hikaye_al_kontrol(h)
        if not gecti:
            kod = "SINIRLI" if bilesik >= config.BILESKE_DIkkat_ESIK else "IZLE"
            sert.extend(engeller[:3])

    if kod == "UYGUN":
        notu = f"Bileşik {bilesik:.0f} (T:{getattr(h, 'teknik_skor', 0):.0f} F:{getattr(h, 'temel_skor', 0):.0f})"
        if aday:
            notu += " — aday listesinde"
        if _tek_hisse_mi(h) and h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM"):
            notu += " · trend teyitli"
        return "UYGUN", ALIM_UYGUN_ETIKET["UYGUN"], notu

    if kod == "SINIRLI":
        notu = "; ".join((sert + yumusak)[:3]) or f"Bileşik {bilesik:.0f} — dikkatli"
        return "SINIRLI", ALIM_UYGUN_ETIKET["SINIRLI"], notu

    if kod == "IZLE":
        notu = "; ".join((sert + yumusak)[:3]) if (sert or yumusak) else f"Bileşik {bilesik:.0f} — izle"
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
