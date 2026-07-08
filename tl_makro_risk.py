# -*- coding: utf-8 -*-
"""
TL makro haber riski — Türkiye'ye özgü kur baskısı sinyalleri.

Orta Doğu arka plan haberlerinden ayrı: faiz indirimi beklentisi ve erken seçim
haberlerinde anormal sıklık TL mevduat kararını etkiler.
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import config

CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")


@dataclass
class TlMakroRiskSonuc:
    faiz_indirim_sayisi: int
    erken_secim_sayisi: int
    faiz_indirim_yuksek: bool
    erken_secim_anormal: bool
    tl_makro_risk_aktif: bool
    kaynak: str
    detay: str = ""


def _conn():
    c = sqlite3.connect(CACHE_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS tl_makro_baseline "
        "(konu TEXT NOT NULL, gun TEXT NOT NULL, sayi INTEGER NOT NULL, ts REAL NOT NULL, "
        "PRIMARY KEY (konu, gun))"
    )
    return c


def baseline_guncelle(konu: str, sayi: int) -> None:
    if sayi < 0:
        return
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT sayi FROM tl_makro_baseline WHERE konu=? AND gun=?",
            (konu, bugun),
        ).fetchone()
        if row:
            yeni = max(int(row[0]), int(sayi))
            conn.execute(
                "UPDATE tl_makro_baseline SET sayi=?, ts=? WHERE konu=? AND gun=?",
                (yeni, time.time(), konu, bugun),
            )
        else:
            conn.execute(
                "INSERT INTO tl_makro_baseline (konu, gun, sayi, ts) VALUES (?, ?, ?, ?)",
                (konu, bugun, int(sayi), time.time()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def taban_median(konu: str, gun: int = 14) -> Optional[float]:
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT sayi FROM tl_makro_baseline WHERE konu=? ORDER BY gun DESC LIMIT ?",
            (konu, gun),
        ).fetchall()
        conn.close()
        if len(rows) < 3:
            return None
        return float(statistics.median(r[0] for r in rows))
    except Exception:
        return None


def _anormal(sayi: int, konu: str, taban_varsayilan: int, carpan: float) -> bool:
    med = taban_median(konu, config.TL_MAKRO_TABAN_GUN)
    taban = int(med) if med is not None else taban_varsayilan
    esik = max(
        int(taban * carpan),
        taban + config.TL_MAKRO_ANORMAL_ARTIS,
    )
    return sayi >= esik


def _secim_anormal(sayi: int, konu: str, taban_varsayilan: int, carpan: float) -> bool:
    """Erken seçim yalnızca karar/ilan odaklı sorgularda ve yüksek mutlak yoğunlukta."""
    karar_esigi = getattr(config, "TL_MAKRO_SECIM_KARAR_ESIGI", 6)
    mutlak = getattr(config, "TL_MAKRO_SECIM_ANORMAL_MUTLAK", 45)
    if sayi < karar_esigi:
        return False
    if sayi >= mutlak:
        return True
    return _anormal(sayi, konu, taban_varsayilan, carpan)


def tl_makro_risk_tara(saat: int = 48) -> TlMakroRiskSonuc:
    from risk_scan import google_news_sayisi

    faiz_sorgular = getattr(
        config,
        "TL_MAKRO_FAIZ_SORGULARI",
        ['"faiz indirimi" beklentisi TCMB Türkiye', '"faiz düşürme" beklentisi Türkiye'],
    )
    secim_sorgular = getattr(
        config,
        "TL_MAKRO_SECIM_SORGULARI",
        [getattr(config, "TL_MAKRO_SECIM_SORGUSU", '"erken seçim kararı" Türkiye')],
    )

    faiz_max = 0
    for sorgu in faiz_sorgular:
        faiz_max = max(faiz_max, google_news_sayisi(sorgu, saat=saat))

    erken_secim = 0
    for sorgu in secim_sorgular:
        erken_secim = max(erken_secim, google_news_sayisi(sorgu, saat=saat))

    baseline_guncelle("faiz_indirim", faiz_max)
    baseline_guncelle("erken_secim", erken_secim)

    faiz_yuksek = faiz_max >= config.TL_MAKRO_FAIZ_ESIGI or _anormal(
        faiz_max,
        "faiz_indirim",
        config.TL_MAKRO_FAIZ_TABAN_VARSAYILAN,
        config.TL_MAKRO_ANORMAL_CARPAN,
    )
    secim_anormal = _secim_anormal(
        erken_secim,
        "erken_secim",
        config.TL_MAKRO_SECIM_TABAN_VARSAYILAN,
        config.TL_MAKRO_ANORMAL_CARPAN,
    )
    aktif = faiz_yuksek or secim_anormal

    parcalar = []
    if faiz_yuksek:
        parcalar.append(f"faiz indirimi beklentisi {faiz_max} haber")
    if secim_anormal:
        parcalar.append(f"erken seçim anormal sıklık {erken_secim} haber")
    detay = f"son {saat}s"
    if parcalar:
        detay += " · " + "; ".join(parcalar)
    else:
        detay += f" · faiz {faiz_max}, erken seçim {erken_secim} (normal)"

    return TlMakroRiskSonuc(
        faiz_indirim_sayisi=faiz_max,
        erken_secim_sayisi=erken_secim,
        faiz_indirim_yuksek=faiz_yuksek,
        erken_secim_anormal=secim_anormal,
        tl_makro_risk_aktif=aktif,
        kaynak="Google News TR (TL makro, tarih filtreli)",
        detay=detay,
    )


def esik_metni() -> str:
    return (
        f"faiz eşiği **{config.TL_MAKRO_FAIZ_ESIGI}** · "
        f"anormal çarpan **{config.TL_MAKRO_ANORMAL_CARPAN}×** taban "
        f"(son {config.SIYASI_RISK_TARAMA_SAAT}s)"
    )
