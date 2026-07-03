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
    """WorldGovernmentBonds CDS API (ücretsiz, key yok)."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.worldgovernmentbonds.com",
        "Referer": "https://www.worldgovernmentbonds.com/cds-historical-data/turkey/5-year/",
        "Content-Type": "application/json",
    }
    try:
        sayfa = requests.get(
            "https://www.worldgovernmentbonds.com/cds-historical-data/turkey/5-year/",
            headers=headers,
            timeout=TIMEOUT,
        )
        m = re.search(r"jsGlobalVars\s*=\s*(\{.*?\});", sayfa.text, re.DOTALL)
        if not m:
            return None
        payload = json.loads(m.group(1))
        endpoint = payload.get("ENDPOINT", "https://www.worldgovernmentbonds.com/wp-json/common/v1/historical")
        r = requests.post(endpoint, json=payload, headers=headers, timeout=TIMEOUT)
        res = r.json().get("result", {})
        val = res.get("ultimoValore") or res.get("lastValData")
        if val is not None and float(val) > 50:
            return float(val)
    except Exception:
        pass
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


def cds_otomatik(
    vix: Optional[float] = None,
    siyasi: int = 5,
    evds_key: str = "",
) -> Tuple[float, str]:
    """Türkiye 5Y CDS (bp) — otomatik."""
    cached = _cache_oku("cds_5y", max_yas_s=1800)
    if cached:
        return cached[0], f"{cached[1]} (önbellek)"

    if evds_key:
        try:
            import data_sources as ds
            items = ds._evds_get("TP.KKTCDS5Y", evds_key, gun_sayisi=30)
            if not items:
                items = ds._evds_get("TP.KTF13", evds_key, gun_sayisi=30)
            if items:
                for item in reversed(items):
                    for k, v in item.items():
                        if k in ("Tarih", "UNIXTIME"):
                            continue
                        if v not in (None, "", "None"):
                            val = float(str(v).replace(",", "."))
                            if val > 50:
                                _cache_yaz("cds_5y", val, "TCMB EVDS")
                                return val, "TCMB EVDS (canlı)"
        except Exception:
            pass

    wgb = _cds_wgb()
    if wgb:
        _cache_yaz("cds_5y", wgb, "WorldGovernmentBonds")
        return wgb, "WorldGovernmentBonds (canlı)"

    bp, kaynak = _cds_piyasa_modeli(vix, siyasi)
    _cache_yaz("cds_5y", bp, kaynak.split("—")[0].strip())
    return bp, kaynak


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


def enflasyon_otomatik(evds_key: str = "") -> Tuple[float, str]:
    """Türkiye yıllık enflasyon (%). Öncelik: EVDS/TÜİK aylık → FRED yıllık → World Bank."""
    cached = _cache_oku("enflasyon_tr", max_yas_s=86400)
    if cached:
        src = cached[1]
        if any(x in src.lower() for x in ("world bank", "fred")):
            return cached[0], f"{src} (önbellek — yıllık/gecikmeli; aylık TÜİK için EVDS TP.FG.J0)"
        return cached[0], f"{src} (önbellek)"

    if evds_key:
        try:
            import data_sources as ds
            for seri, etiket in (
                ("TP.FG.J0", "TÜFE yıllık değişim"),
                ("TP.FG.J01", "TÜFE endeks"),
            ):
                items = ds._evds_get(seri, evds_key, gun_sayisi=400)
                if items:
                    for item in reversed(items):
                        for k, v in item.items():
                            if k in ("Tarih", "UNIXTIME"):
                                continue
                            if v not in (None, "", "None"):
                                val = float(str(v).replace(",", "."))
                                _cache_yaz("enflasyon_tr", val, "TCMB EVDS")
                                return val, f"TCMB EVDS {seri} — {etiket} (TÜİK, resmi)"
        except Exception:
            pass

    for deneme in range(2):
        fred = _fred_csv_son("FPCPITOTLZGTUR")
        if fred is not None:
            _cache_yaz("enflasyon_tr", fred, "FRED yıllık TÜFE")
            return fred, "FRED FPCPITOTLZGTUR — yıllık TÜFE (gecikmeli; aylık TÜİK için EVDS önerilir)"
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


def tcmb_faizi_otomatik(evds_key: str = "") -> Tuple[float, str]:
    """TCMB politika / fonlama faizi (%). Öncelik: EVDS → manuel → YKB proxy."""
    cached = _cache_oku("tcmb_faizi", max_yas_s=3600)
    if cached:
        src = cached[1]
        if "YKB" in src or "türetilmiş" in src.lower() or "tahmin" in src.lower():
            return cached[0], f"{src} (önbellek — banka proxy, EVDS/manuel teyit önerilir)"
        return cached[0], f"{src} (önbellek)"

    if evds_key:
        try:
            import data_sources as ds
            for seri in (
                "TP.KTF21",       # 1 hafta vadeli repo
                "TP.APIFON4",
                "TP.API.REP.ORT.G214",
                "TP.KTF17",
            ):
                items = ds._evds_get(seri, evds_key, gun_sayisi=60)
                if items:
                    for item in reversed(items):
                        for k, v in item.items():
                            if k in ("Tarih", "UNIXTIME"):
                                continue
                            if v not in (None, "", "None"):
                                raw = float(str(v).replace(",", "."))
                                val = raw if raw > 1 else raw * 100
                                if 5 < val < 100:
                                    _cache_yaz("tcmb_faizi", val, "TCMB EVDS")
                                    return val, f"TCMB EVDS {seri} — politika/piyasa faizi (resmi)"
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
