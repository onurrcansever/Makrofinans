# -*- coding: utf-8 -*-
"""
Siyasi haber eşikleri — 14 günlük taban + sabit alt sınırlar (temkin 70, kriz 85).
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import time
from datetime import datetime
from typing import Dict, List, Optional

import config

CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")
TABAN_MIN_GUN = 7  # "14g taban" etiketi için minimum geçmiş gün


def _conn():
    c = sqlite3.connect(CACHE_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS siyasi_baseline "
        "(gun TEXT PRIMARY KEY, sayi INTEGER NOT NULL, ts REAL NOT NULL)"
    )
    return c


def baseline_guncelle(sayi: int) -> None:
    """Günlük Kapı 1 sayımını kaydet (günde bir kez, günün en yüksek okuması)."""
    if sayi < 0:
        return
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT sayi FROM siyasi_baseline WHERE gun=?", (bugun,)
        ).fetchone()
        if row:
            yeni = max(int(row[0]), int(sayi))
            conn.execute(
                "UPDATE siyasi_baseline SET sayi=?, ts=? WHERE gun=?",
                (yeni, time.time(), bugun),
            )
        else:
            conn.execute(
                "INSERT INTO siyasi_baseline (gun, sayi, ts) VALUES (?, ?, ?)",
                (bugun, int(sayi), time.time()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def taban_sayilar(gun: int = 14, *, bugun_haric: bool = True) -> List[int]:
    """Son N günün günlük Kapı 1 sayaçları (bugün hariç)."""
    try:
        conn = _conn()
        bugun = datetime.now().strftime("%Y-%m-%d")
        if bugun_haric:
            rows = conn.execute(
                "SELECT sayi FROM siyasi_baseline WHERE gun < ? ORDER BY gun DESC LIMIT ?",
                (bugun, gun),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sayi FROM siyasi_baseline ORDER BY gun DESC LIMIT ?",
                (gun,),
            ).fetchall()
        conn.close()
        return [int(r[0]) for r in rows]
    except Exception:
        return []


def taban_median(gun: int = 14, *, bugun_haric: bool = True) -> Optional[float]:
    """Son N günün günlük sayaç medyanı (bugün hariç)."""
    vals = taban_sayilar(gun, bugun_haric=bugun_haric)
    if len(vals) < 3:
        return None
    return float(statistics.median(vals))


def _referans_taban() -> int:
    """Yeterli geçmiş yokken güncel okumaya yapışmayan referans taban."""
    return max(14, config.SIYASI_RISK_TABAN_VARSAYILAN - 10)


def esikler() -> Dict[str, int]:
    """
    Temkin ve kriz eşikleri.
    taban = son 14g minimum (≥7 gün geçmiş) veya kısıtlı medyan (3–6 gün) veya referans
    temkin = max(70, taban × 1.25)
    kriz   = max(85, taban × 1.5)
    """
    gun = config.SIYASI_RISK_TABAN_GUN
    vals = taban_sayilar(gun, bugun_haric=True)
    n = len(vals)
    if n >= TABAN_MIN_GUN:
        taban = int(min(vals))
        ornek = gun
        kaynak = "14g_min"
    elif n >= 3:
        taban = int(statistics.median(vals))
        ornek = n
        kaynak = "kisitli"
    else:
        taban = _referans_taban()
        ornek = 0
        kaynak = "referans"

    temkin = max(config.SIYASI_RISK_TEMKIN_ESIGI, int(taban * 1.25))
    kriz = max(config.SIYASI_RISK_KRIZ_ESIGI, int(taban * 1.5))
    return {
        "taban": taban,
        "temkin": temkin,
        "kriz": kriz,
        "ornek_gun": ornek,
        "ornek_sayisi": n,
        "taban_kaynak": kaynak,
    }


def esik_metni(guncel: Optional[int] = None) -> str:
    e = esikler()
    kaynak = e.get("taban_kaynak", "referans")
    n = e.get("ornek_sayisi", 0)
    if kaynak == "14g_min":
        kaynak_txt = f"14g min taban **{e['taban']}** ({n} gün)"
    elif kaynak == "kisitli":
        kaynak_txt = f"kısıtlı geçmiş medyan taban **{e['taban']}** ({n} gün — ısınma)"
    else:
        kaynak_txt = f"referans taban **{e['taban']}** (yeterli geçmiş yok)"

    ek = ""
    if guncel is not None and guncel == e["taban"]:
        if kaynak != "14g_min":
            ek = " · güncel sayım tabana yakın (dar bant / ısınma)"
        elif n >= TABAN_MIN_GUN and len(set(taban_sayilar(config.SIYASI_RISK_TABAN_GUN))) <= 2:
            ek = " · sayım dar bantta — taban bilgi değeri sınırlı"

    return (
        f"{kaynak_txt} · temkin **{e['temkin']}** · kriz **{e['kriz']}** "
        f"(son {config.SIYASI_RISK_TARAMA_SAAT} saat, tarih filtreli){ek}"
    )
