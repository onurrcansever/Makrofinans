# -*- coding: utf-8 -*-
"""TEFAS stopaj — iktisap dilimine göre sayısal matris (getiriden düşülmez).

Kaynak özeti: GVK Geç. 67; 09.07.2025 sonrası genel %17,5 (10041 sayılı karar);
TEFAS hisse senedi yoğun fonlar %0. Banka/TEFAS ekranı nihai.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from tefas_universe import _norm_fon_ad

STOPAJ_CAPTION = (
    "Stopaj satış anında; oran iktisap (alış) dilimine göre. "
    "Varsayılan: yeni iktisap (≥09.07.2025). Getiriler brüttür — skor/% getiriden düşülmez. "
    "Banka/TEFAS ekranını esas alın."
)

# Dilim anahtarları (yeniden eskiye)
DONEM_YENI = "yeni_20250709"  # ≥ 09.07.2025
DONEM_202502 = "202502_202507"  # 01.02.2025 – 08.07.2025
DONEM_202411 = "202411_202501"  # 01.11.2024 – 31.01.2025
DONEM_202405 = "202405_202410"  # 01.05.2024 – 31.10.2024
DONEM_202012 = "202012_202404"  # 23.12.2020 – 30.04.2024

VARSAYILAN_DONEM = DONEM_YENI

# Sınıf → dönem → oran (yüzde puan, örn. 17.5)
# Hisse yoğun her dilimde 0; diğerleri 09.07.2025+ için 17.5
_TEFAS_STOPAJ_MATRIS: Dict[str, Dict[str, float]] = {
    "hisse": {
        DONEM_YENI: 0.0,
        DONEM_202502: 0.0,
        DONEM_202411: 0.0,
        DONEM_202405: 0.0,
        DONEM_202012: 0.0,
    },
    "para_piyasasi": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 7.5,
        DONEM_202012: 0.0,
    },
    "katilim": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 7.5,
        DONEM_202012: 0.0,
    },
    "altin_emtia": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 7.5,
        DONEM_202012: 0.0,
    },
    "borclanma": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 7.5,
        DONEM_202012: 0.0,
    },
    "fon_sepeti": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 7.5,
        DONEM_202012: 0.0,
    },
    "degisken": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 10.0,
        DONEM_202012: 10.0,
    },
    "serbest_doviz": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 10.0,
        DONEM_202012: 10.0,
    },
    "diger": {
        DONEM_YENI: 17.5,
        DONEM_202502: 15.0,
        DONEM_202411: 10.0,
        DONEM_202405: 10.0,
        DONEM_202012: 10.0,
    },
}

_DONEM_ETIKET = {
    DONEM_YENI: "",
    DONEM_202502: "iktisap 02/25–07/25",
    DONEM_202411: "iktisap 11/24–01/25",
    DONEM_202405: "iktisap 05/24–10/24",
    DONEM_202012: "iktisap 12/20–04/24",
}


def _sinif_anahtar(
    *,
    ad: str,
    kategori: str,
    hisse_pct: Optional[float],
) -> str:
    n = _norm_fon_ad(ad)
    kat = (kategori or "").strip().lower()

    hisse_yogun = (
        kat == "hisse"
        or "HISSE SENEDI YOGUN" in n
        or (hisse_pct is not None and hisse_pct >= 80.0)
    )
    if hisse_yogun:
        return "hisse"

    if (
        kat == "serbest_doviz"
        or "DOVIZ" in n
        or "YABANCI" in n
        or "EUROBOND" in n
        or ("AVRO" in n and "SERBEST" in n)
    ):
        return "serbest_doviz"

    if kat in _TEFAS_STOPAJ_MATRIS:
        return kat
    return "diger"


def _fmt_oran(oran: float) -> str:
    if abs(oran - round(oran)) < 1e-9:
        return f"%{int(round(oran))}"
    s = f"{oran:.1f}".replace(".", ",")
    return f"%{s}"


def tefas_stopaj_sinifi(
    *,
    ad: str = "",
    kategori: str = "",
    hisse_pct: Optional[float] = None,
    iktisap_donemi: str = VARSAYILAN_DONEM,
) -> Tuple[str, float, str]:
    """(etiket, oran_pct, not) — sayısal stopaj; kesin beyanname hesabı değildir."""
    donem = iktisap_donemi if iktisap_donemi in _DONEM_ETIKET else VARSAYILAN_DONEM
    sinif = _sinif_anahtar(ad=ad, kategori=kategori, hisse_pct=hisse_pct)
    matris = _TEFAS_STOPAJ_MATRIS.get(sinif) or _TEFAS_STOPAJ_MATRIS["diger"]
    oran = float(matris.get(donem, matris[VARSAYILAN_DONEM]))

    etiket = _fmt_oran(oran)
    ekstra = _DONEM_ETIKET.get(donem) or ""
    if ekstra and donem != VARSAYILAN_DONEM:
        etiket = f"{etiket} · {ekstra}"

    if sinif == "hisse":
        not_ = "Hisse senedi yoğun (TEFAS) — stopaj %0 (özet; banka teyidi)."
    elif sinif == "serbest_doviz":
        not_ = (
            f"Döviz/yabancı içerik — matris {_fmt_oran(oran)} "
            f"(iktisap dilimi); banka/TEFAS ekranını doğrulayın."
        )
    else:
        not_ = (
            f"Matris {_fmt_oran(oran)} — iktisap dilimi "
            f"{'yeni (≥09.07.2025)' if donem == VARSAYILAN_DONEM else ekstra}. "
            "Banka ekranı esas."
        )
    return etiket, oran, not_
