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
from typing import Dict, Optional

import config

CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")


def _conn():
    c = sqlite3.connect(CACHE_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS siyasi_baseline "
        "(gun TEXT PRIMARY KEY, sayi INTEGER NOT NULL, ts REAL NOT NULL)"
    )
    return c


def baseline_guncelle(sayi: int) -> None:
    """Günlük siyasi haber sayısını kaydet (günde bir kez, günün en yüksek okuması)."""
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


def taban_median(gun: int = 14) -> Optional[float]:
    """Son N günün günlük sayaç medyanı."""
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT sayi FROM siyasi_baseline ORDER BY gun DESC LIMIT ?",
            (gun,),
        ).fetchall()
        conn.close()
        if len(rows) < 3:
            return None
        return float(statistics.median(r[0] for r in rows))
    except Exception:
        return None


def esikler() -> Dict[str, int]:
    """
    Temkin ve kriz eşikleri.
    taban = max(14g medyan, varsayılan 52)
    temkin = max(70, taban × 1.25)
    kriz   = max(85, taban × 1.5)
    """
    gun = config.SIYASI_RISK_TABAN_GUN
    med = taban_median(gun)
    taban = int(med) if med is not None else config.SIYASI_RISK_TABAN_VARSAYILAN
    temkin = max(config.SIYASI_RISK_TEMKIN_ESIGI, int(taban * 1.25))
    kriz = max(config.SIYASI_RISK_KRIZ_ESIGI, int(taban * 1.5))
    return {
        "taban": taban,
        "temkin": temkin,
        "kriz": kriz,
        "ornek_gun": gun if med is not None else 0,
    }


def esik_metni() -> str:
    e = esikler()
    kaynak = f"14g medyan taban **{e['taban']}**" if e["ornek_gun"] else f"varsayılan taban **{e['taban']}**"
    return (
        f"{kaynak} · temkin **{e['temkin']}** · kriz **{e['kriz']}** "
        f"(son 48 saat, tarih filtreli)"
    )
