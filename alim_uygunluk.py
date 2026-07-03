# -*- coding: utf-8 -*-
"""
Alım uygunluk etiketi — tablo/PDF'de her varlık için tek bakışta karar özeti.
Finansal tavsiye değil; teknik + trend + profil + aday listesi birleşimi.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Set, Tuple

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

ALIM_UYGUN_ETIKET = {
    "UYGUN": "🟢 Alım için uygun",
    "SINIRLI": "🟡 Dikkatli — sınırlı uygun",
    "UYGUN_DEGIL": "🔴 Alım için uygun değil",
    "IZLE": "⚪ İzle / bekle",
}

# Tablo/PDF — tek kelime, kesilmeden okunur
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


def _degerlendir(
    h: "HisseAnaliz",
    aday_semboller: Set[str],
    esik: float,
) -> Tuple[str, str, str]:
    aday = h.sembol in aday_semboller
    trend = h.trend_notu or ""
    profil = h.profil_notu or ""
    rejim = h.rejim_notu or ""

    if h.fiyat is None or h.sinyal == "VERI_YOK":
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], "Fiyat/veri yok"

    if h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], "Aşırı alım veya yüksek risk"

    if h.sinyal == "BEKLE" or "Trend filtresi: BEKLE" in trend:
        neden = "Trend zayıf veya sinyal yok"
        if "1 ay düşüş" in trend:
            neden = "Son 1 ay düşüş — trend alımı iptal"
        elif "SMA200 altı" in trend:
            neden = "SMA200 altı — ana trend zayıf"
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], neden

    if h.sinyal not in ("ALIM_FIRSATI", "TREND_ALIM"):
        return "IZLE", ALIM_UYGUN_ETIKET["IZLE"], "Net alım sinyali yok"

    if h.skor < esik:
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], f"Skor eşiğin altında (<{esik:.0f})"

    sert: List[str] = []
    yumusak: List[str] = []

    if not aday:
        sert.append("Profil/aday listesinde değil")

    if trend.startswith("Uyarı:") and h.degisim_1ay is not None and h.degisim_1ay < -4:
        sert.append(trend.replace("Uyarı:", "").strip()[:50])
    elif trend.startswith("Uyarı:"):
        yumusak.append(trend.replace("Uyarı:", "").strip()[:40])

    if profil and profil != "Profil uyumlu":
        pl = profil.lower()
        if any(x in pl for x in ("baskılanır", "önerilmez", "kaldırıldı", "tek hisse önerilmez")):
            sert.append("Profil ile uyumsuz")
        elif "ikincil" in pl and "uyumlu" not in pl:
            yumusak.append("Profilde ikincil öncelik")

    if rejim and rejim != "Rejim uyumlu":
        rl = rejim.lower()
        if any(x in rl for x in ("kaçın", "uzak dur", "baskılanır")):
            sert.append("Makro rejim baskısı")
        elif any(x in rl for x in ("ikincil", "sınırlı")):
            yumusak.append("Rejimde ikincil")

    if h.zirve_52h_pct is not None and h.zirve_52h_pct >= 97:
        yumusak.append("52H zirve bölgesi")

    if h.degisim_1ay is not None and -5 <= h.degisim_1ay < -2.5:
        yumusak.append(f"1 ay {h.degisim_1ay:+.1f}%")

    if h.peer_yuzdelik is not None and h.peer_yuzdelik < 25:
        yumusak.append("Sektör içi zayıf")

    if h.haber_notu and any(x in h.haber_notu.lower() for x in ("olumsuz", "düşür", "bekle")):
        sert.append("Haber baskısı")

    if sert:
        if aday:
            return "SINIRLI", ALIM_UYGUN_ETIKET["SINIRLI"], "; ".join(sert[:2])
        return "UYGUN_DEGIL", ALIM_UYGUN_ETIKET["UYGUN_DEGIL"], "; ".join(sert[:2])

    if aday and not yumusak:
        tip = "ETF adayı" if h.piyasa == "ETF" else "Hisse adayı"
        return "UYGUN", ALIM_UYGUN_ETIKET["UYGUN"], f"{tip} — teknik + trend + profil uyumlu"

    if aday and yumusak:
        return "SINIRLI", ALIM_UYGUN_ETIKET["SINIRLI"], "; ".join(yumusak[:2])

    if yumusak:
        return "SINIRLI", ALIM_UYGUN_ETIKET["SINIRLI"], "; ".join(yumusak[:2])

    return "IZLE", ALIM_UYGUN_ETIKET["IZLE"], "İzleme — henüz aday değil"


def alim_uygunluk_uygula(
    hisseler: List["HisseAnaliz"],
    aday_semboller: Set[str],
    esik: float,
) -> None:
    for h in hisseler:
        kod, etiket, notu = _degerlendir(h, aday_semboller, esik)
        h.alim_uygun = kod
        h.alim_uygun_etiket = etiket
        h.alim_uygun_not = notu
