# -*- coding: utf-8 -*-
"""
Revolut'ta sık işlem gören UCITS ETF evreni.
Yahoo Finance sembolleri (borsa soneki: .L Londra, .DE Xetra, .AS Amsterdam).
Revolut'ta ISIN veya ticker ile arayın — liste EEA platformu odaklıdır.
"""
from __future__ import annotations

from typing import List, Tuple

# (yahoo_sembol, ad, sektor, isin, revolut_ticker)
# sektor: dunya | abd | gelisen | altin | tahvil | teknoloji | temettu | avrupa | esg
REVOLUT_ETFLER: List[Tuple[str, str, str, str, str]] = [
    # ── Çekirdek portföy (en çok önerilen) ──
    ("VWCE.DE", "Vanguard FTSE All-World UCITS (Acc)", "dunya", "IE00BK5BQT80", "VWCE"),
    ("CSPX.L", "iShares Core S&P 500 UCITS (Acc)", "abd", "IE00B5BMR087", "CSPX"),
    ("VUAA.L", "Vanguard S&P 500 UCITS (Acc)", "abd", "IE00BFMXXD54", "VUAA"),
    ("IWDA.AS", "iShares Core MSCI World UCITS (Acc)", "dunya", "IE00B4L5Y983", "IWDA"),
    ("XDWD.DE", "Xtrackers MSCI World UCITS (Acc)", "dunya", "IE00BJ0KDR00", "XDWD"),
    ("SPPW.DE", "SPDR MSCI World UCITS (Acc)", "dunya", "IE00BFY0GT14", "SPPW"),
    # ── Bölgesel / tema ──
    ("EQQQ.L", "Invesco EQQQ Nasdaq-100 UCITS", "teknoloji", "IE0032077012", "EQQQ"),
    ("EMIM.L", "iShares Core MSCI EM IMI UCITS (Acc)", "gelisen", "IE00BKM4GZ66", "EMIM"),
    ("IS3N.DE", "iShares MSCI EM IMI UCITS (Acc)", "gelisen", "IE00BKM4GZ66", "IS3N"),
    ("IEMA.L", "iShares MSCI EM Asia UCITS", "gelisen", "IE00B5L8K969", "IEMA"),
    ("VEUR.L", "Vanguard FTSE Developed Europe UCITS", "avrupa", "IE00B945VV12", "VEUR"),
    ("VUKE.L", "Vanguard FTSE 100 UCITS", "avrupa", "IE00B810Q511", "VUKE"),
    ("EXSA.DE", "iShares STOXX Europe 600 UCITS", "avrupa", "DE0002635307", "EXSA"),
    ("VGER.L", "Vanguard FTSE Germany UCITS", "avrupa", "IE00B95PGT31", "VGER"),
    ("EUNA.DE", "iShares MSCI North America UCITS", "abd", "IE00B14X4M10", "EUNA"),
    ("SXR8.DE", "iShares Core DAX UCITS (Acc)", "avrupa", "DE0005933931", "SXR8"),
    # ── Temettü / dağıtım ──
    ("VHYL.L", "Vanguard FTSE All-World High Div UCITS", "temettu", "IE00B8GKDB10", "VHYL"),
    ("VUSA.L", "Vanguard S&P 500 UCITS (Dist)", "abd", "IE00B3XXRP09", "VUSA"),
    ("VWRL.L", "Vanguard FTSE All-World UCITS (Dist)", "dunya", "IE00B3RBWM25", "VWRL"),
    ("IDVY.L", "iShares EM Dividend UCITS", "temettu", "IE00B652H904", "IDVY"),
    # ── Koruma / tahvil ──
    ("SGLD.L", "iShares Physical Gold ETC", "altin", "IE00B4ND3602", "SGLD"),
    ("VAGP.L", "Vanguard Global Aggregate Bond UCITS", "tahvil", "IE00BG47KH54", "VAGP"),
    # ── ESG ──
    ("IUSQ.DE", "iShares MSCI World SRI UCITS (Acc)", "esg", "IE00BYV2GR82", "IUSQ"),
    # ── ABD tema (Revolut dışı; tarama evreni) ──
    ("ITA", "iShares US Aerospace Defense ETF", "savunma_uzay", "US4642875237", "ITA"),
]

ETF_ETIKET = {
    "dunya": "Küresel hisse",
    "abd": "ABD hisse",
    "gelisen": "Gelişen piyasa",
    "altin": "Altın",
    "tahvil": "Tahvil",
    "teknoloji": "Teknoloji/Nasdaq",
    "temettu": "Temettü",
    "avrupa": "Avrupa",
    "esg": "ESG/Sürdürülebilir",
    "savunma_uzay": "Savunma / Uzay",
}

# Makro rejimde öncelik sırası (düşük = daha önce öner)
ETF_REJIM_ONCELIGI = {
    "TL_FIRSAT": ("abd", "dunya", "temettu", "avrupa", "tahvil", "altin", "teknoloji", "gelisen", "esg"),
    "ENFLASYON_KORUMA": ("altin", "tahvil", "temettu", "dunya", "abd", "avrupa", "esg", "teknoloji", "gelisen"),
    "RISK_ON": ("teknoloji", "abd", "dunya", "gelisen", "esg", "temettu", "avrupa", "tahvil", "altin"),
    "KRIZ": ("tahvil", "altin", "temettu", "dunya", "abd", "avrupa", "esg", "teknoloji", "gelisen"),
    "EM_STRES": ("tahvil", "altin", "temettu", "dunya", "abd", "avrupa", "esg", "teknoloji", "gelisen"),
    "NOTR": ("dunya", "abd", "teknoloji", "temettu", "avrupa", "tahvil", "altin", "gelisen", "esg"),
}


def etf_oncelik(sektor: str, makro_rejim: str) -> int:
    sira = ETF_REJIM_ONCELIGI.get(makro_rejim, ETF_REJIM_ONCELIGI["NOTR"])
    try:
        return sira.index(sektor)
    except ValueError:
        return len(sira)
