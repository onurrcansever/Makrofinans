# -*- coding: utf-8 -*-
"""
Spot emtia evreni — fiziksel altın/gümüş için Yahoo sürekli vadeli (front-month).
GC=F / SI=F: USD/oz; tarama tablosu + signal engine v2.
"""
from __future__ import annotations

from typing import List, Tuple

# (yahoo_sembol, ad, sektor, quote_currency)
# piyasa sabiti: EMTIA · varlik_turu: emtia
EMTIA_SEMBOLLER: List[Tuple[str, str, str, str]] = [
    ("GC=F", "Altın (ons)", "altin", "USD"),
    ("SI=F", "Gümüş (ons)", "gumus", "USD"),
]

EMTIA_ETIKET = {
    "altin": "Altın",
    "gumus": "Gümüş",
}

# Troy ons → gram (ISO)
ONS_GRAM = 31.1034768


def tum_emtalar() -> List[Tuple[str, str, str, str, str, str]]:
    """(sembol, ad, piyasa, sektor, isin, revolut) — tum_evren uyumu."""
    return [(s, a, "EMTIA", k, "", "") for s, a, k, _pb in EMTIA_SEMBOLLER]


def emtia_quote_currency(sembol: str) -> str:
    sym = (sembol or "").strip().upper()
    for s, _a, _k, pb in EMTIA_SEMBOLLER:
        if s.upper() == sym:
            return pb
    return "USD"


def gram_tl_from_oz(oz_usd: float, usd_try: float, *, ons_gram: float = ONS_GRAM) -> float:
    """Spot ons USD → TL/gram: (oz / 31.1035) × USDTRY."""
    if oz_usd is None or usd_try is None:
        raise ValueError("oz_usd ve usd_try gerekli")
    oz = float(oz_usd)
    kur = float(usd_try)
    if oz <= 0 or kur <= 0 or ons_gram <= 0:
        raise ValueError("pozitif oz/kur/ons_gram gerekli")
    return (oz / ons_gram) * kur


def gram_tl_metin(oz_usd: float, usd_try: float, *, nd: int = 0) -> str:
    """UI hücresi: 'Gram: ~6.031 TL'."""
    try:
        g = gram_tl_from_oz(oz_usd, usd_try)
    except (TypeError, ValueError):
        return "—"
    if nd <= 0:
        return f"Gram: ~{g:,.0f} TL".replace(",", ".")
    return f"Gram: ~{g:,.{nd}f} TL"
