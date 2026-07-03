# -*- coding: utf-8 -*-
"""
Yapı Kredi — otomatik vadeli mevduat faizi (key gerekmez)
=========================================================
Resmi web sitesindeki e-mevduat hesaplama aracının public AJAX uç noktası:
  POST .../e-mevduat-faizi-hesaplama.aspx/GetCalculationToolInqury

Kaynak: yapikredi.com.tr hesaplama aracı (klasik vadeli mevduat, 100.000 TL referans).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests

TIMEOUT = 15
_CACHE_TTL = 3600  # 1 saat
_CACHE: Dict[str, object] = {"ts": 0.0, "data": None}

API_BASE = (
    "https://www.yapikredi.com.tr/bireysel-bankacilik/hesaplama-araclari/"
    "e-mevduat-faizi-hesaplama.aspx"
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MakroPortfoyAsistani/1.0)",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "JQuery PageEvents",
}

# Referans tutar: 50–250 bin TL dilimindeki oranlar
DEFAULT_TUTAR_TL = 100_000
VADE_GUN = {"tl_3ay": 92, "tl_6ay": 181, "tl_1y": 365}


@dataclass
class YapikrediMevduat:
    tl_3ay_brut: float
    tl_6ay_brut: float
    tl_1y_brut: float
    tutar_tl: float
    urun: str
    kaynak: str
    cekim_zamani: str


def stopaj_orani(gun: int, doviz: str = "TL") -> float:
    """Türkiye mevduat stopajı (2026 — Yapı Kredi stopaj tablosu ile uyumlu)."""
    if doviz != "TL":
        return 0.25
    if gun <= 180:
        return 0.10
    if gun <= 365:
        return 0.075
    return 0.05


def net_brut_oran(brut_yuzde: float, gun: int, doviz: str = "TL") -> float:
    """Brüt yıllık % → net yıllık oran (ondalık)."""
    brut = brut_yuzde / 100 if brut_yuzde > 1 else brut_yuzde
    return brut * (1 - stopaj_orani(gun, doviz))


def _sorgu(tutar: float, gun: int, e_mevduat: bool) -> Optional[float]:
    payload = {
        "amount": tutar,
        "tenor": gun,
        "currency": "YTL",
        "eDeposite": e_mevduat,
    }
    try:
        r = requests.post(
            f"{API_BASE}/GetCalculationToolInqury",
            headers=_HEADERS,
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        govde = r.json()
        data = govde.get("d", {}).get("Data")
        if not data or data.get("ErrorMessage"):
            return None
        faiz = data.get("InterestRate")
        return float(faiz) if faiz is not None else None
    except Exception as e:
        print(f"[UYARI] Yapı Kredi faiz sorgusu ({gun} gün): {e}")
        return None


def _tek_vade(tutar: float, gun: int) -> Tuple[Optional[float], str]:
    """Klasik ve e-mevduat oranlarından yüksek olanı al (en güncel teklif)."""
    klasik = _sorgu(tutar, gun, e_mevduat=False)
    emev = _sorgu(tutar, gun, e_mevduat=True)
    if klasik is None and emev is None:
        return None, "yok"
    if klasik is None:
        return emev, "e-mevduat"
    if emev is None or klasik >= emev:
        return klasik, "klasik vadeli"
    return emev, "e-mevduat"


def yapikredi_tl_faizleri(
    tutar_tl: float = DEFAULT_TUTAR_TL,
    cache_kullan: bool = True,
) -> Optional[YapikrediMevduat]:
    """Yapı Kredi'den TL mevduat brüt faizlerini çeker (% cinsinden, örn. 41.0)."""
    simdi = time.time()
    if cache_kullan and _CACHE["data"] and simdi - float(_CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["data"]  # type: ignore[return-value]

    oranlar: Dict[str, float] = {}
    urunler: Dict[str, str] = {}
    for anahtar, gun in VADE_GUN.items():
        faiz, urun = _tek_vade(tutar_tl, gun)
        if faiz is None:
            return None
        oranlar[anahtar] = faiz
        urunler[anahtar] = urun

    urun_ozet = urunler["tl_1y"] if len(set(urunler.values())) == 1 else "karışık (klasik/e-mevduat)"
    sonuc = YapikrediMevduat(
        tl_3ay_brut=oranlar["tl_3ay"],
        tl_6ay_brut=oranlar["tl_6ay"],
        tl_1y_brut=oranlar["tl_1y"],
        tutar_tl=tutar_tl,
        urun=urun_ozet,
        kaynak=f"Yapı Kredi canlı ({urun_ozet}, {tutar_tl:,.0f} TL)",
        cekim_zamani=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    _CACHE["ts"] = simdi
    _CACHE["data"] = sonuc
    return sonuc
