# -*- coding: utf-8 -*-
"""TEFAS fon evreni — Yapı Kredi + Kuveyt Türk Portföy sınıflandırma."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# TEFAS fund_name içinde geçen marka parçaları (_norm_fon_ad sonrası)
YK_PORTFOY_MARKA = "YAPI KRED"
KT_PORTFOY_MARKA = "KUVEYT TURK"
PORTFOY_MARKALARI = (YK_PORTFOY_MARKA, KT_PORTFOY_MARKA)

KATEGORILER = {
    "para_piyasasi": "Para piyasası / kısa vade",
    "borclanma": "Borçlanma / tahvil",
    "degisken": "Değişken / karma",
    "hisse": "Hisse senedi yoğun",
    "serbest_doviz": "Serbest (döviz)",
    "altin_emtia": "Altın / emtia / kıymetli maden",
    "fon_sepeti": "Fon sepeti",
    "katilim": "Katılım",
    "diger": "Diğer",
}

PARA_BIRIMI = {
    "TL": "TL",
    "USD": "USD / Dolar",
    "EUR": "Avro",
    "GBP": "Pound",
    "KARISIK": "Karışık / belirsiz",
}


def _norm_fon_ad(fund_name: str) -> str:
    n = (fund_name or "").upper()
    for src, dst in (("İ", "I"), ("Ö", "O"), ("Ü", "U"), ("Ş", "S"), ("Ç", "C"), ("Ğ", "G")):
        n = n.replace(src, dst)
    return n


def evren_fon_mu(fund_name: str) -> bool:
    """Yapı Kredi veya Kuveyt Türk Portföy fonu mu?"""
    n = _norm_fon_ad(fund_name)
    return any(m in n for m in PORTFOY_MARKALARI)


def yk_fon_mu(fund_name: str) -> bool:
    """Geriye uyum — evren filtresi (YK + Kuveyt Türk)."""
    return evren_fon_mu(fund_name)


def kt_fon_mu(fund_name: str) -> bool:
    return KT_PORTFOY_MARKA in _norm_fon_ad(fund_name)


def portfoy_sirketi(fund_name: str) -> str:
    """Fon kurucusu / portföy şirketi (kısa etiket)."""
    n = _norm_fon_ad(fund_name)
    if YK_PORTFOY_MARKA in n:
        return "Yapı Kredi"
    if KT_PORTFOY_MARKA in n:
        return "Kuveyt Türk"
    return "Diğer"


def fon_kategorisi(fund_name: str) -> str:
    n = _norm_fon_ad(fund_name)
    if "PARA PIYASASI" in n or "KISA VADELI BORCLANMA" in n:
        return "para_piyasasi"
    if "HISSE SENEDI" in n or "ENDEKS" in n and "HISSE" in n:
        return "hisse"
    if "ALTIN" in n or "GUMUS" in n or "EMTIA" in n or "KIYMETLI MADEN" in n:
        return "altin_emtia"
    if "FON SEPETI" in n:
        return "fon_sepeti"
    if "KATILIM" in n:
        return "katilim"
    if "SERBEST" in n and ("DOVIZ" in n or "AVRO" in n or "DOLAR" in n or "POUND" in n):
        return "serbest_doviz"
    if "BORCLANMA" in n or "EUROBOND" in n or "TLREF" in n or "KIRA SERTIFIKA" in n:
        return "borclanma"
    if "DEGISKEN" in n or "KARMA" in n or "COKLU VARLIK" in n:
        return "degisken"
    return "diger"


# EUR/EURO/AVRO ayrı token (EUROBOND / EURONEXT false-positive olmasın)
_EUR_PB_RE = re.compile(r"(?<![A-Z0-9])(?:EUR|EURO|AVRO)(?![A-Z0-9])")


def fon_para_birimi(fund_name: str) -> str:
    n = _norm_fon_ad(fund_name)
    raw = fund_name or ""
    if "AVRO" in n or "(EUR" in n or _EUR_PB_RE.search(n) or "€" in raw:
        return "EUR"
    if "POUND" in n or re.search(r"(?<![A-Z0-9])GBP(?![A-Z0-9])", n):
        return "GBP"
    if "DOVIZ" in n or "DOLAR" in n or re.search(r"(?<![A-Z0-9])USD(?![A-Z0-9])", n):
        return "USD"
    if "(TL)" in n or " SERBEST FON)" in n and "DOVIZ" not in n:
        return "TL"
    if "KATILIM" in n and "DOVIZ" not in n:
        return "TL"
    return "KARISIK"


TEFAS_FIYAT_PB = frozenset({"TL", "EUR", "USD", "GBP"})


def tefas_fiyat_kaynak_pb(para_birimi: str) -> Optional[str]:
    """Fon adından türetilen fiyat PB — KARISIK portföy karışımı değil, fiyat birimi."""
    pb = (para_birimi or "").upper()
    return pb if pb in TEFAS_FIYAT_PB else None


def kisa_fon_adi(fund_name: str, max_len: int = 48) -> str:
    s = re.sub(r"\s+", " ", (fund_name or "").strip())
    for prefix in (
        "YAPI KREDİ PORTFÖY ",
        "YAPI KREDI PORTFOY ",
        "KUVEYT TÜRK PORTFÖY ",
        "KUVEYT TURK PORTFOY ",
        "KUVEYT TÜRK PORTFOY ",
        "KUVEYT TURK PORTFÖY ",
    ):
        s = s.replace(prefix, "")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def populer_yk_kodlari() -> List[str]:
    """Sık karşılaşılan YK + Kuveyt Türk fonları — hızlı karşılaştırma için."""
    return [
        # Yapı Kredi
        "YLB", "YPT", "PPI", "YVD", "YIK", "PKT",
        "YHS", "YEF", "YKT", "YAE", "YDP", "YAK",
        "YGM", "YPC", "PLA", "YMH", "YBE", "YHT",
        # Kuveyt Türk Portföy
        "KLU", "KSV", "KTV", "KTN", "KTR", "KZL",
        "KPC", "KTM", "KAV", "KTJ", "KUT", "KCV",
    ]
