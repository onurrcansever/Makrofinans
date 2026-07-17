# -*- coding: utf-8 -*-
"""
Hisse evreni — genişletilmiş BIST / S&P 500 / NASDAQ listeleri + sektör etiketleri.
Yahoo Finance sembolleri; BIST için .IS soneki.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from emtia_universe import EMTIA_ETIKET, tum_emtalar
from etf_universe import ETF_ETIKET, REVOLUT_ETFLER

# (sembol, ad, sektör)
# sektör: defansif | buyume | finans | enerji | sanayi | tuketim | teknoloji | savunma | hava | holding
BIST_HISSELER: List[Tuple[str, str, str]] = [
    ("THYAO.IS", "Turk Hava Yollari", "hava"),
    ("PGSUS.IS", "Pegasus", "hava"),
    ("GARAN.IS", "Garanti BBVA", "finans"),
    ("AKBNK.IS", "Akbank", "finans"),
    ("YKBNK.IS", "Yapi Kredi", "finans"),
    ("ISCTR.IS", "Is Bankasi", "finans"),
    ("HALKB.IS", "Halkbank", "finans"),
    ("VAKBN.IS", "Vakifbank", "finans"),
    ("BIMAS.IS", "BIM", "tuketim"),
    ("MGROS.IS", "Migros", "tuketim"),
    ("SOKM.IS", "Sok Marketler", "tuketim"),
    ("ASELS.IS", "Aselsan", "savunma"),
    ("KCHOL.IS", "Koc Holding", "holding"),
    ("SAHOL.IS", "Sabanci Holding", "holding"),
    ("EREGL.IS", "Erdemir", "sanayi"),
    ("TUPRS.IS", "Tupras", "enerji"),
    ("PETKM.IS", "Petkim", "enerji"),
    ("SISE.IS", "Sisecam", "sanayi"),
    ("FROTO.IS", "Ford Otosan", "sanayi"),
    ("TOASO.IS", "Tofas", "sanayi"),
    ("TCELL.IS", "Turkcell", "teknoloji"),
    ("TTKOM.IS", "Turk Telekom", "teknoloji"),
    ("ENKAI.IS", "Enka Insaat", "sanayi"),
    ("EKGYO.IS", "Emlak Konut GYO", "finans"),
    ("ENJSA.IS", "Enerjisa", "enerji"),
    ("AKSEN.IS", "Aksa Enerji", "enerji"),
    ("ARCLK.IS", "Arcelik", "tuketim"),
    ("DOAS.IS", "Dogus Otomotiv", "tuketim"),
    ("TAVHL.IS", "TAV Havalimanlari", "hava"),
    ("HEKTS.IS", "Hektas", "sanayi"),
    ("ODAS.IS", "Odas Elektrik", "sanayi"),
    ("KRDMD.IS", "Kardemir", "sanayi"),
]

SP500_HISSELER: List[Tuple[str, str, str]] = [
    ("AAPL", "Apple", "teknoloji"),
    ("MSFT", "Microsoft", "teknoloji"),
    ("GOOGL", "Alphabet", "teknoloji"),
    ("AMZN", "Amazon", "teknoloji"),
    ("NVDA", "NVIDIA", "teknoloji"),
    ("META", "Meta", "teknoloji"),
    ("BRK-B", "Berkshire", "finans"),
    ("JPM", "JPMorgan", "finans"),
    ("V", "Visa", "finans"),
    ("MA", "Mastercard", "finans"),
    ("UNH", "UnitedHealth", "defansif"),
    ("JNJ", "Johnson", "defansif"),
    ("PG", "Procter & Gamble", "defansif"),
    ("KO", "Coca-Cola", "defansif"),
    ("PEP", "PepsiCo", "defansif"),
    ("WMT", "Walmart", "defansif"),
    ("LLY", "Eli Lilly", "defansif"),
    ("MRK", "Merck", "defansif"),
    ("ABBV", "AbbVie", "defansif"),
    ("XOM", "Exxon", "enerji"),
    ("CVX", "Chevron", "enerji"),
    ("HD", "Home Depot", "tuketim"),
    ("COST", "Costco", "tuketim"),
    ("DIS", "Disney", "tuketim"),
    ("BA", "Boeing", "sanayi"),
    ("GS", "Goldman Sachs", "finans"),
    ("BAC", "Bank of America", "finans"),
    ("PFE", "Pfizer", "defansif"),
    ("TMO", "Thermo Fisher", "defansif"),
    ("CRM", "Salesforce", "teknoloji"),
    ("ORCL", "Oracle", "teknoloji"),
    ("AMD", "AMD", "teknoloji"),
    ("NFLX", "Netflix", "teknoloji"),
    ("TSLA", "Tesla", "buyume"),
]

NASDAQ_HISSELER: List[Tuple[str, str, str]] = [
    ("NVDA", "NVIDIA", "teknoloji"),
    ("AAPL", "Apple", "teknoloji"),
    ("MSFT", "Microsoft", "teknoloji"),
    ("GOOGL", "Alphabet", "teknoloji"),
    ("AMZN", "Amazon", "teknoloji"),
    ("META", "Meta", "teknoloji"),
    ("TSLA", "Tesla", "buyume"),
    ("AVGO", "Broadcom", "teknoloji"),
    ("COST", "Costco", "defansif"),
    ("NFLX", "Netflix", "teknoloji"),
    ("AMD", "AMD", "teknoloji"),
    ("QCOM", "Qualcomm", "teknoloji"),
    ("ADBE", "Adobe", "teknoloji"),
    ("INTC", "Intel", "teknoloji"),
    ("CSCO", "Cisco", "teknoloji"),
    ("INTU", "Intuit", "teknoloji"),
    ("AMAT", "Applied Materials", "teknoloji"),
    ("MU", "Micron", "teknoloji"),
    ("LRCX", "Lam Research", "teknoloji"),
    ("KLAC", "Klam", "teknoloji"),
    ("PANW", "Palo Alto Networks", "teknoloji"),
    ("CRWD", "CrowdStrike", "teknoloji"),
    ("MRVL", "Marvell", "teknoloji"),
    ("ABNB", "Airbnb", "buyume"),
    ("PYPL", "PayPal", "teknoloji"),
    ("SBUX", "Starbucks", "tuketim"),
    ("GILD", "Gilead", "defansif"),
    ("ISRG", "Intuitive Surgical", "defansif"),
    ("REGN", "Regeneron", "defansif"),
]

ENDEKSLER = {
    "BIST 100": "XU100.IS",
    "NASDAQ Composite": "^IXIC",
    "NASDAQ 100": "^NDX",
    "S&P 500": "^GSPC",
}

SEKTOR_ETIKET = {
    "defansif": "Defansif",
    "buyume": "Büyüme",
    "finans": "Finans",
    "enerji": "Enerji",
    "sanayi": "Sanayi",
    "tuketim": "Tüketim",
    "teknoloji": "Teknoloji",
    "savunma": "Savunma",
    "hava": "Havacılık",
    "holding": "Holding",
    **ETF_ETIKET,
    **EMTIA_ETIKET,
}


def tum_hisseler() -> List[Tuple[str, str, str, str]]:
    """
    (sembol, ad, piyasa, sektor) — her sembol tek kez.
    Çift listelenen mega-cap'ler (hem S&P 500 hem NASDAQ) NASDAQ olarak sınıflanır;
    aksi halde aynı hisse iki kez analiz edilip mükerrer öneri üretir.
    """
    nasdaq_sem = {s for s, _, _ in NASDAQ_HISSELER}
    out: List[Tuple[str, str, str, str]] = []
    for s, a, k in BIST_HISSELER:
        out.append((s, a, "BIST", k))
    for s, a, k in SP500_HISSELER:
        if s not in nasdaq_sem:
            out.append((s, a, "SP500", k))
    for s, a, k in NASDAQ_HISSELER:
        out.append((s, a, "NASDAQ", k))
    return out


def tum_etflar() -> List[Tuple[str, str, str, str, str, str]]:
    """(yahoo, ad, piyasa, sektor, isin, revolut_ticker)"""
    return [(s, a, "ETF", k, isin, rt) for s, a, k, isin, rt in REVOLUT_ETFLER]


def tum_evren() -> List[Tuple[str, str, str, str, str, str]]:
    """Hisse + ETF + spot emtia birleşik evren."""
    out: List[Tuple[str, str, str, str, str, str]] = [
        (s, a, p, k, "", "") for s, a, p, k in tum_hisseler()
    ]
    out.extend(tum_etflar())
    out.extend(tum_emtalar())
    return out


def sembol_sektor(sembol: str, piyasa: str) -> str:
    for s, _, k in BIST_HISSELER:
        if s == sembol and piyasa == "BIST":
            return k
    for s, _, k in SP500_HISSELER:
        if s == sembol and piyasa == "SP500":
            return k
    for s, _, k in NASDAQ_HISSELER:
        if s == sembol and piyasa == "NASDAQ":
            return k
    for s, _, k, _, _ in REVOLUT_ETFLER:
        if s == sembol and piyasa == "ETF":
            return k
    return "sanayi"
