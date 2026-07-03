# -*- coding: utf-8 -*-
"""
Otomatik veri kaynakları — manuel giriş yok.
EVDS key varsa ek seriler devreye girer; yoksa canlı alternatifler kullanılır.
"""
import os
import sqlite3
import time
from typing import Optional, Tuple

import config
from macro_auto import cds_otomatik, enflasyon_otomatik, tcmb_faizi_otomatik

DEFAULT_SIYASI_RISK = 3
CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")


def _yf_son(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if h.empty:
            return None
        return float(h["Close"].iloc[-1])
    except Exception:
        return None


def fed_faizi_al(api_key: str = "") -> Tuple[float, str]:
    if api_key:
        try:
            import requests
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": "DFF",
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
                timeout=10,
            )
            r.raise_for_status()
            v = float(r.json()["observations"][0]["value"])
            return v, "FRED DFF — Fed efektif fon faizi (günlük)"
        except Exception:
            pass

    from macro_auto import _fred_csv_son
    dff = _fred_csv_son("DFF")
    if dff is not None:
        return dff, "FRED DFF — Fed efektif fon faizi (CSV, key gerekmez)"

    irx = _yf_son("^IRX")
    if irx is not None:
        return irx, (
            "Yahoo ^IRX — 13 haftalık Hazine bonosu (proxy, Fed DFF değil · gecikmeli)"
        )

    return 4.33, "Acil yedek — Fed kaynağına ulaşılamadı"


def enflasyon_al(api_key: str = "") -> Tuple[float, str]:
    return enflasyon_otomatik(api_key or config.EVDS_API_KEY)


def cds_al(manuel: dict = None, vix: Optional[float] = None, siyasi: int = 5) -> Tuple[float, str]:
    return cds_otomatik(vix=vix, siyasi=siyasi, evds_key=config.EVDS_API_KEY)


def _gdelt_cache_oku(anahtar: str) -> Optional[int]:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gdelt_cache (key TEXT PRIMARY KEY, ts REAL, count INTEGER)"
        )
        row = conn.execute("SELECT ts, count FROM gdelt_cache WHERE key=?", (anahtar,)).fetchone()
        conn.close()
        if row and time.time() - row[0] < 6 * 3600:
            return int(row[1])
    except Exception:
        pass
    return None


def _gdelt_cache_yaz(anahtar: str, count: int) -> None:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gdelt_cache (key TEXT PRIMARY KEY, ts REAL, count INTEGER)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO gdelt_cache (key, ts, count) VALUES (?, ?, ?)",
            (anahtar, time.time(), count),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def siyasi_risk_al(kelimeler: list) -> Tuple[int, str]:
    cache_key = "siyasi"
    cached = _gdelt_cache_oku(cache_key)
    if cached is not None:
        return cached, "GDELT (önbellek, 6 saat)"

    import data_sources as ds
    for deneme in range(2):
        try:
            n = ds.gdelt_makale_sayisi(kelimeler)
            if n is not None:
                _gdelt_cache_yaz(cache_key, n)
                return n, "GDELT (canlı)"
        except Exception:
            pass
        time.sleep(1.5 * (deneme + 1))

    _gdelt_cache_yaz(cache_key, DEFAULT_SIYASI_RISK)
    return DEFAULT_SIYASI_RISK, "GDELT yedek (ağ hatası)"


def savas_risk_al(kelimeler: list = None) -> Tuple[int, str, bool]:
    """Jeopolitik/savaş — Google News TR + GDELT. (sayi, kaynak, guvenilir)"""
    from risk_scan import jeopolitik_risk_tara

    cache_key = "savas_v2"
    cached = _gdelt_cache_oku(cache_key)
    if cached is not None and cached > 0:
        return cached, "Google News TR (önbellek, 6 saat)", True

    sonuc = jeopolitik_risk_tara()
    if sonuc.guvenilir and sonuc.sayi > 0:
        _gdelt_cache_yaz(cache_key, sonuc.sayi)
    kaynak = sonuc.kaynak
    if sonuc.detay:
        kaynak = f"{kaynak} · {sonuc.detay}"
    return sonuc.sayi, kaynak, sonuc.guvenilir


def rezerv_trend_al(api_key: str = "") -> Tuple[Optional[bool], str]:
    if not api_key:
        return None, "EVDS key yok — rezerv trendi atlandı"
    try:
        import data_sources as ds
        r = ds.tcmb_reserves_trend(api_key)
        if r:
            durum = "Artıyor" if r["artiyor"] else "Azalıyor"
            return r["artiyor"], f"TCMB EVDS ({durum})"
    except Exception:
        pass
    return None, "EVDS rezerv verisi alınamadı"


def tcmb_faizi_al(manuel: dict = None) -> Tuple[Optional[float], str]:
    return tcmb_faizi_otomatik(config.EVDS_API_KEY)
