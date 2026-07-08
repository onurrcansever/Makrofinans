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


def enflasyon_al(api_key: str = "", taze: bool = False) -> Tuple[float, str]:
    return enflasyon_otomatik(api_key or config.EVDS_API_KEY, taze=taze)


def cds_al(
    manuel: dict = None,
    vix: Optional[float] = None,
    siyasi: int = 5,
    savas: int = 0,
    taze: bool = False,
) -> Tuple[float, str]:
    return cds_otomatik(vix=vix, siyasi=siyasi, taze=taze, savas=savas)


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


def siyasi_risk_al(kelimeler: list, taze: bool = False) -> Tuple[int, str]:
    from risk_scan import siyasi_risk_say

    cache_key = "siyasi_v2"
    saat = config.SIYASI_RISK_TARAMA_SAAT
    if not taze:
        cached = _gdelt_cache_oku(cache_key)
        if cached is not None:
            return cached, f"Google News (önbellek, 6 saat · son {saat}s)"

    n, kaynak, detay = siyasi_risk_say(kelimeler, saat=saat)
    if n <= 0:
        n = DEFAULT_SIYASI_RISK
        kaynak = f"{kaynak} · yedek {DEFAULT_SIYASI_RISK}"

    if not taze:
        _gdelt_cache_yaz(cache_key, n)
    if detay:
        kaynak = f"{kaynak} · {detay}"
    return n, kaynak


def savas_risk_al(kelimeler: list = None, taze: bool = False) -> Tuple[int, str, bool]:
    """Jeopolitik/savaş — Google News TR + GDELT. (sayi, kaynak, guvenilir)"""
    from risk_scan import jeopolitik_risk_tara

    cache_key = "savas_v2"
    if not taze:
        cached = _gdelt_cache_oku(cache_key)
        if cached is not None and cached > 0:
            return cached, "Google News TR (önbellek, 6 saat)", True

    sonuc = jeopolitik_risk_tara(hizli=taze)
    if sonuc.guvenilir and sonuc.sayi > 0 and not taze:
        _gdelt_cache_yaz(cache_key, sonuc.sayi)
    kaynak = sonuc.kaynak
    if sonuc.detay:
        kaynak = f"{kaynak} · {sonuc.detay}"
    return sonuc.sayi, kaynak, sonuc.guvenilir


def tl_makro_risk_al(taze: bool = False) -> Tuple[dict, str]:
    """TL makro haber — faiz indirimi beklentisi, erken seçim sıçraması."""
    from tl_makro_risk import tl_makro_risk_tara

    sonuc = tl_makro_risk_tara(saat=config.SIYASI_RISK_TARAMA_SAAT)
    veri = {
        "tl_makro_risk_aktif": sonuc.tl_makro_risk_aktif,
        "tl_faiz_indirim_haber": sonuc.faiz_indirim_sayisi,
        "tl_erken_secim_haber": sonuc.erken_secim_sayisi,
        "tl_erken_secim_anormal": sonuc.erken_secim_anormal,
    }
    kaynak = sonuc.kaynak
    if sonuc.detay:
        kaynak = f"{kaynak} · {sonuc.detay}"
    return veri, kaynak


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


def tcmb_faizi_al(manuel: dict = None, taze: bool = False) -> Tuple[Optional[float], str]:
    return tcmb_faizi_otomatik(config.EVDS_API_KEY, taze=taze)
