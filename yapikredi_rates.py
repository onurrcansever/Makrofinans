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

import config

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

# Döviz mevduat asgari tutarları (YKB şart koşar; altında API hata verir)
DOVIZ_MIN_TUTAR = {"USD": 25_000, "EUR": 50_000}
_DOVIZ_CACHE: Dict[str, object] = {"ts": 0.0, "data": None}


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
    """Türkiye mevduat stopajı — config.TL_STOPAJ_TABLOSU (varsayılan %15 TL)."""
    if doviz != "TL":
        return config.DOVIZ_STOPAJ_ORANI
    for max_gun, oran in config.TL_STOPAJ_TABLOSU:
        if gun <= max_gun:
            return oran
    return config.TL_STOPAJ_ORAN


def net_brut_oran(brut_yuzde: float, gun: int, doviz: str = "TL") -> float:
    """Brüt yıllık % → net yıllık oran (ondalık)."""
    brut = brut_yuzde / 100 if brut_yuzde > 1 else brut_yuzde
    return brut * (1 - stopaj_orani(gun, doviz))


def _sorgu(tutar: float, gun: int, e_mevduat: bool, currency: str = "YTL") -> Optional[float]:
    payload = {
        "amount": tutar,
        "tenor": gun,
        "currency": currency,
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
        print(f"[UYARI] Yapı Kredi faiz sorgusu ({currency} {gun} gün): {e}")
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
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {anahtar: ex.submit(_tek_vade, tutar_tl, gun) for anahtar, gun in VADE_GUN.items()}
        for anahtar, fut in futs.items():
            faiz, urun = fut.result()
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


@dataclass
class YapikrediDovizMevduat:
    usd_1y_brut: Optional[float]  # yıllık brüt % (örn. 0.01)
    eur_1y_brut: Optional[float]
    kaynak: str
    cekim_zamani: str


def _doviz_tek(doviz: str, gun: int = 365) -> Optional[float]:
    """Tek döviz için brüt yıllık % — klasik ve e-mevduattan yükseği."""
    tutar = DOVIZ_MIN_TUTAR.get(doviz, 50_000)
    adaylar = [
        _sorgu(tutar, gun, e_mevduat=True, currency=doviz),
        _sorgu(tutar, gun, e_mevduat=False, currency=doviz),
    ]
    gecerli = [a for a in adaylar if a is not None]
    return max(gecerli) if gecerli else None


def yapikredi_doviz_faizleri(cache_kullan: bool = True) -> Optional[YapikrediDovizMevduat]:
    """Yapı Kredi'den USD/EUR mevduat brüt faizlerini çeker (% cinsinden).

    Bellek (1 saat) + disk önbelleği (mevduat TTL) — hesaplama aracının
    public AJAX ucu, TL ile aynı kaynak. Asgari tutarlar: 25k USD / 50k EUR.
    """
    simdi = time.time()
    if cache_kullan and _DOVIZ_CACHE["data"] and simdi - float(_DOVIZ_CACHE["ts"]) < _CACHE_TTL:
        return _DOVIZ_CACHE["data"]  # type: ignore[return-value]

    def _uret():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            usd_fut = ex.submit(_doviz_tek, "USD")
            eur_fut = ex.submit(_doviz_tek, "EUR")
            usd, eur = usd_fut.result(), eur_fut.result()
        if usd is None and eur is None:
            return None
        return YapikrediDovizMevduat(
            usd_1y_brut=usd,
            eur_1y_brut=eur,
            kaynak="Yapı Kredi canlı (hesaplama aracı, 365 gün)",
            cekim_zamani=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    try:
        from disk_onbellek import TTL, disk_getir_swr
        sonuc = disk_getir_swr("ykb:doviz_mevduat", TTL["mevduat"], _uret)
    except Exception:
        sonuc = _uret()
    if sonuc is not None:
        _DOVIZ_CACHE["ts"] = simdi
        _DOVIZ_CACHE["data"] = sonuc
    return sonuc
