# -*- coding: utf-8 -*-
"""
Otomatik Makro Veri — manuel giriş yok
=======================================
CDS, enflasyon, TCMB faizi ve EUR/TRY volatilitesi canlı veya gecikmeli
kaynaklardan çekilir. Başarısız olursa şeffaf piyasa modeli devreye girer.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import requests

import config

CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")
TIMEOUT = 12
_CACHE: dict = {"ts": 0.0}


def _cache_oku(anahtar: str, max_yas_s: int = 3600) -> Optional[Tuple[float, str, str]]:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS macro_cache "
            "(key TEXT PRIMARY KEY, ts REAL, value REAL, kaynak TEXT, meta TEXT)"
        )
        row = conn.execute(
            "SELECT ts, value, kaynak, meta FROM macro_cache WHERE key=?", (anahtar,)
        ).fetchone()
        conn.close()
        if row and time.time() - row[0] < max_yas_s:
            return float(row[1]), row[2], row[3] or ""
    except Exception:
        pass
    return None


def _cache_yaz(anahtar: str, deger: float, kaynak: str, meta: str = "") -> None:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS macro_cache "
            "(key TEXT PRIMARY KEY, ts REAL, value REAL, kaynak TEXT, meta TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO macro_cache (key, ts, value, kaynak, meta) VALUES (?, ?, ?, ?, ?)",
            (anahtar, time.time(), deger, kaynak, meta),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _fred_csv_son(seri: str) -> Optional[float]:
    try:
        r = requests.get(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={seri}",
            timeout=TIMEOUT,
            headers={"User-Agent": "MacroPortfolio/1.0"},
        )
        if r.status_code != 200 or not r.text.startswith("DATE"):
            return None
        for satir in reversed(r.text.strip().split("\n")):
            if satir.startswith("DATE") or not satir.strip():
                continue
            parca = satir.split(",")
            if len(parca) >= 2 and parca[1] not in (".", "", "NaN"):
                return float(parca[1])
    except Exception:
        pass
    return None


def _eurtry_volatilite(gun: int = 90) -> Optional[float]:
    try:
        bitis = datetime.now().date()
        baslangic = bitis - timedelta(days=gun + 5)
        r = requests.get(
            f"https://api.frankfurter.app/{baslangic}..{bitis}",
            params={"from": "EUR", "to": "TRY"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        kurlar = [v["TRY"] for v in r.json().get("rates", {}).values()]
        if len(kurlar) < 10:
            return None
        getiriler = [(kurlar[i] / kurlar[i - 1] - 1) for i in range(1, len(kurlar))]
        return statistics.stdev(getiriler) * (252 ** 0.5)
    except Exception:
        return None


def _cds_wgb() -> Optional[float]:
    """WorldGovernmentBonds — data_sources.turkiye_cds_5y_wgb sarmalayıcı."""
    try:
        import data_sources as ds
        sonuc = ds.turkiye_cds_5y_wgb()
        return sonuc[0] if sonuc else None
    except Exception:
        return None


def _cds_piyasa_modeli(vix: Optional[float], siyasi: int) -> Tuple[float, str]:
    vol = _eurtry_volatilite(90) or 0.18
    vix = vix or 20.0
    # Kalibre edilmiş şeffaf model — CDS ~ f(vol, VIX, siyasi haber)
    bp = 165.0
    bp += vol * 1000
    bp += max(0.0, vix - 15.0) * 2.8
    bp += min(siyasi, 20) * 2.5
    bp = max(150.0, min(550.0, bp))
    return bp, (
        f"Piyasa modeli (EUR/TRY vol %{vol*100:.1f}, VIX {vix:.1f}, "
        f"siyasi haber {siyasi}) — gecikmeli CDS proxy"
    )


def _manuel_cds() -> Optional[Tuple[float, str]]:
    try:
        path = os.path.join(os.path.dirname(__file__), "manual_inputs.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        cds = m.get("cds_5y_bp")
        tarih = m.get("guncelleme_tarihi")
        if cds is None:
            return None
        val = float(cds)
        tarih_not = f", güncelleme {tarih}" if tarih else ""
        return val, f"manual_inputs.json — manuel CDS{tarih_not} (haftalık teyit önerilir)"
    except Exception:
        return None


def cds_otomatik(
    vix: Optional[float] = None,
    siyasi: int = 5,
    evds_key: str = "",
    taze: bool = False,
    savas: int = 0,
) -> Tuple[float, str]:
    """Türkiye 5Y CDS (bp) — çapraz doğrulamalı."""
    from cds_guven import cds_guvenli_al

    sonuc = cds_guvenli_al(vix=vix, siyasi=siyasi, savas=savas, taze=taze)
    meta = sonuc.kaynak
    if sonuc.ham is not None and abs(sonuc.ham - sonuc.deger) > 1:
        meta += f" · ham okuma {sonuc.ham:.0f} bp"
    if not sonuc.dogrulandi:
        meta += " · ⚠ çapraz teyit yok"
    return sonuc.deger, meta


def _enflasyon_worldbank() -> Optional[float]:
    try:
        r = requests.get(
            "https://api.worldbank.org/v2/country/TUR/indicator/FP.CPI.TOTL.ZG",
            params={"format": "json", "per_page": 5, "date": "2020:2026"},
            timeout=TIMEOUT,
            headers={"User-Agent": "MacroPortfolio/1.0"},
        )
        r.raise_for_status()
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
    except Exception:
        pass
    return None


def enflasyon_cache_temizle() -> None:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute("DELETE FROM macro_cache WHERE key=?", ("enflasyon_tr",))
        conn.commit()
        conn.close()
    except Exception:
        pass


def enflasyon_otomatik(evds_key: str = "", taze: bool = False) -> Tuple[float, str]:
    """Türkiye yıllık enflasyon (%). Öncelik: enflasyon_resmi.json → EVDS → FRED."""
    from enflasyon_kaynak import enflasyon_manuel_son, enflasyon_resmi_al

    manuel = enflasyon_manuel_son()
    if manuel is not None:
        taze = True

    if not taze:
        cached = _cache_oku("enflasyon_tr", max_yas_s=86400)
        if cached and not manuel:
            src = cached[1]
            if any(x in src.lower() for x in ("world bank", "fred", "acil yedek")):
                return cached[0], f"{src} (önbellek — yıllık/gecikmeli; aylık TÜİK için EVDS TP.FG.J0/J01)"
            if "gecikmeli" in src.lower() or "⚠" in src:
                return cached[0], f"{src} (önbellek)"
            return cached[0], f"{src} (önbellek)"

    deger, kaynak, uyarilar = enflasyon_resmi_al(evds_key or config.EVDS_API_KEY)
    if deger is not None:
        if uyarilar:
            kaynak = f"{kaynak} — {' '.join(uyarilar[:1])}"
        _cache_yaz("enflasyon_tr", deger, kaynak.split("—")[0].strip())
        return deger, kaynak

    for deneme in range(2):
        fred = _fred_csv_son("FPCPITOTLZGTUR")
        if fred is not None:
            _cache_yaz("enflasyon_tr", fred, "FRED yıllık TÜFE")
            return (
                fred,
                "FRED FPCPITOTLZGTUR — yıllık TÜFE (gecikmeli; aylık TÜİK için EVDS önerilir)",
            )
        if deneme == 0:
            time.sleep(1.5)

    wb = _enflasyon_worldbank()
    if wb is not None:
        _cache_yaz("enflasyon_tr", wb, "World Bank yıllık TÜFE")
        return wb, "World Bank FP.CPI.TOTL.ZG — yıllık TÜFE (gecikmeli; TÜİK/EVDS değil)"

    val = float(os.getenv("ENFLASYON_TR_VARSAYILAN", "35"))
    return val, "Acil yedek — resmi enflasyon kaynağına ulaşılamadı"


def _manuel_tcmb() -> Optional[Tuple[float, str]]:
    try:
        path = os.path.join(os.path.dirname(__file__), "manual_inputs.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        tcmb = m.get("tcmb_politika_faizi")
        tarih = m.get("guncelleme_tarihi")
        if tcmb is None:
            return None
        val = float(tcmb)
        if val <= 1:
            val *= 100
        tarih_not = f", güncelleme {tarih}" if tarih else ""
        return val, f"manual_inputs.json — manuel TCMB faizi{tarih_not}"
    except Exception:
        return None


def tcmb_faizi_otomatik(evds_key: str = "", taze: bool = False) -> Tuple[float, str]:
    """TCMB politika faizi (%). Öncelik: TCMB.gov (PPK repo) → manuel → YKB proxy.
    Not: EVDS TP.APIFON4 ağırlıklı ortalama fonlama maliyetidir (~%40), politika faizi değil."""
    del evds_key  # rezerv/enflasyon için EVDS; politika faizi tcmb.gov.tr
    if not taze:
        cached = _cache_oku("tcmb_faizi", max_yas_s=3600)
        if cached:
            src = cached[1].lower()
            yanlis = any(x in src for x in ("apifon4", "aofm", "fonlama maliyeti"))
            if not yanlis:
                if "ykb" in src or "türetilmiş" in src or "tahmin" in src:
                    return cached[0], f"{cached[1]} (önbellek — banka proxy, TCMB.gov teyit önerilir)"
                return cached[0], f"{cached[1]} (önbellek)"

    try:
        import data_sources as ds
        ppk = ds.tcmb_politika_faizi_resmi()
        if ppk:
            val, kaynak = ppk
            _cache_yaz("tcmb_faizi", val, kaynak.split("—")[0].strip())
            return val, kaynak
    except Exception:
        pass

    manuel = _manuel_tcmb()
    if manuel:
        _cache_yaz("tcmb_faizi", manuel[0], "Manuel")
        return manuel

    try:
        from yapikredi_rates import yapikredi_tl_faizleri
        ykb = yapikredi_tl_faizleri()
        if ykb:
            piyasa = max(ykb.tl_3ay_brut, ykb.tl_6ay_brut)
            tahmini = round(piyasa * 0.902, 2)
            _cache_yaz("tcmb_faizi", tahmini, "YKB türetilmiş")
            return tahmini, (
                f"Proxy: Yapı Kredi piyasa %{piyasa:.1f} → tahmini TCMB ~%{tahmini:.1f} "
                f"(resmi değil — EVDS veya manual_inputs.json önerilir)"
            )
    except Exception:
        pass

    val = 37.0
    return val, "Acil yedek — TCMB kaynağına ulaşılamadı"
