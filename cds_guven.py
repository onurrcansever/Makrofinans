# -*- coding: utf-8 -*-
"""
CDS doğrulama — Bloomberg Terminal + Investing.com otomatik; manuel giriş yok.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import config

CACHE_DB = os.getenv("MARKET_CACHE_DB", "market_cache.db")
CDS_CACHE_KEY = "cds_5y"
MANUAL_PATH = os.path.join(os.path.dirname(__file__), "manual_inputs.json")


@dataclass
class CdsSonuc:
    deger: float
    kaynak: str
    ham: Optional[float] = None
    dogrulandi: bool = False
    uyari: List[str] = field(default_factory=list)
    kaynaklar: Dict[str, float] = field(default_factory=dict)
    onay_bekliyor: bool = False


def _manuel_cds_yedek() -> Optional[float]:
    """API yoksa yedek — otomatik senkron manual_inputs (kullanıcı girişi değil)."""
    try:
        if os.path.isfile(MANUAL_PATH):
            with open(MANUAL_PATH, encoding="utf-8") as f:
                d = json.load(f)
            v = d.get("cds_5y_bp")
            if v is not None and float(v) > 50:
                return float(v)
    except Exception:
        pass
    return None


def _rel_fark(a: float, b: float) -> float:
    ort = (a + b) / 2.0
    if ort <= 0:
        return 0.0
    return abs(a - b) / ort


def _onceki_deger() -> Optional[float]:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS macro_cache "
            "(key TEXT PRIMARY KEY, ts REAL, value REAL, kaynak TEXT, meta TEXT)"
        )
        row = conn.execute(
            "SELECT value FROM macro_cache WHERE key=?", (CDS_CACHE_KEY,)
        ).fetchone()
        conn.close()
        if row:
            return float(row[0])
    except Exception:
        pass
    return None


def _cache_yaz(deger: float, kaynak: str) -> None:
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS macro_cache "
            "(key TEXT PRIMARY KEY, ts REAL, value REAL, kaynak TEXT, meta TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO macro_cache (key, ts, value, kaynak, meta) VALUES (?, ?, ?, ?, ?)",
            (CDS_CACHE_KEY, time.time(), deger, kaynak, ""),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _otomatik_referans_yaz(deger: float, kaynak: str) -> None:
    """manual_inputs.json — yalnızca sistem otomatik senkron (kullanıcı girişi değil)."""
    if os.getenv("CDS_OTO_REFERANS_YAZ", "1").strip() in ("0", "false", "no"):
        return
    try:
        mevcut = {}
        if os.path.isfile(MANUAL_PATH):
            with open(MANUAL_PATH, encoding="utf-8") as f:
                mevcut = json.load(f)
        mevcut["cds_5y_bp"] = round(float(deger), 2)
        mevcut["guncelleme_tarihi"] = datetime.now().strftime("%Y-%m-%d")
        mevcut["cds_guncelleme_notu"] = f"Otomatik API senkron — {kaynak[:80]}"
        with open(MANUAL_PATH, "w", encoding="utf-8") as f:
            json.dump(mevcut, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        pass


def cds_guvenli_al(
    vix: Optional[float] = None,
    siyasi: int = 5,
    savas: int = 0,
    taze: bool = False,
) -> CdsSonuc:
    """
    Bloomberg Terminal (varsa) + Investing.com — çapraz doğrulama.
    Manuel kullanıcı girişi kullanılmaz.
    """
    from cds_bloomberg import turkiye_cds_5y_bloomberg_blp
    from data_sources import (
        investing_cds_son_meta,
        turkiye_cds_5y_investing_detay,
        turkiye_cds_5y_investing_kapanis,
        turkiye_cds_5y_wgb,
    )
    from macro_auto import _cds_piyasa_modeli

    capraz = float(os.getenv("CDS_CAPRAZ_ESIGI", "0.10"))
    fark_bp_esik = config.CDS_KAYNAK_FARK_BP

    if not taze:
        try:
            conn = sqlite3.connect(CACHE_DB)
            row = conn.execute(
                "SELECT ts, value, kaynak FROM macro_cache WHERE key=?",
                (CDS_CACHE_KEY,),
            ).fetchone()
            conn.close()
            if row and time.time() - row[0] < 1800:
                return CdsSonuc(
                    deger=float(row[1]),
                    kaynak=f"{row[2]} (önbellek)",
                    dogrulandi=True,
                )
        except Exception:
            pass

    kaynaklar: Dict[str, float] = {}
    meta: Dict[str, str] = {}

    blp = turkiye_cds_5y_bloomberg_blp()
    if blp:
        kaynaklar["bloomberg"] = blp[0]
        meta["bloomberg"] = blp[1]

    inv_detay = turkiye_cds_5y_investing_detay()
    if inv_detay:
        kaynaklar["investing_canli"] = inv_detay.deger
        meta["investing_canli"] = inv_detay.kaynak

    inv_kapanis = turkiye_cds_5y_investing_kapanis()
    if inv_kapanis:
        kaynaklar["investing_kapanis"] = inv_kapanis[0]
        meta["investing_kapanis"] = inv_kapanis[1]

    wgb = turkiye_cds_5y_wgb()
    if wgb:
        kaynaklar["wgb"] = wgb[0]
        meta["wgb"] = wgb[1]

    manuel = _manuel_cds_yedek()
    if manuel:
        kaynaklar["manual_yedek"] = manuel
        meta["manual_yedek"] = "manual_inputs.json (otomatik yedek)"

    inv_meta = investing_cds_son_meta()
    uyari: List[str] = []
    if inv_meta.get("gecikmeli"):
        gg = inv_meta.get("gecikme_gun", "?")
        dv = inv_meta.get("deger")
        dv_txt = f"{dv:.0f}" if dv is not None else "?"
        uyari.append(
            f"Investing **Geciken veri** (+{gg} gün) — sitede {dv_txt} bp."
        )

    bloomberg_bp = kaynaklar.get("bloomberg")
    inv_vals = [
        kaynaklar[k]
        for k in ("investing_canli", "investing_kapanis")
        if k in kaynaklar
    ]
    inv_bp = float(sorted(inv_vals)[len(inv_vals) // 2]) if inv_vals else None

    deger: Optional[float] = None
    kaynak = ""
    dogrulandi = False

    if bloomberg_bp is not None and inv_bp is not None:
        bp_fark = abs(bloomberg_bp - inv_bp)
        if bp_fark <= fark_bp_esik and _rel_fark(bloomberg_bp, inv_bp) <= capraz:
            deger = float((bloomberg_bp + inv_bp) / 2.0)
            dogrulandi = True
            kaynak = (
                f"Bloomberg + Investing çapraz doğrulandı ({deger:.0f} bp; "
                f"BB {bloomberg_bp:.0f}, Inv {inv_bp:.0f})"
            )
        else:
            deger = float(max(bloomberg_bp, inv_bp))
            dogrulandi = True
            kaynak = (
                f"Muhafazakâr CDS ({deger:.0f} bp) — "
                f"Bloomberg {bloomberg_bp:.0f} vs Investing {inv_bp:.0f} bp "
                f"(fark {bp_fark:.0f} bp > {fark_bp_esik:.0f})"
            )
            uyari.append(
                f"CDS kaynak farkı {bp_fark:.0f} bp — ortalama yerine yüksek değer "
                f"**{deger:.0f}** bp kullanıldı."
            )
    elif bloomberg_bp is not None:
        deger = float(bloomberg_bp)
        dogrulandi = True
        kaynak = meta.get("bloomberg", "Bloomberg Terminal")
    elif inv_bp is not None:
        deger = float(inv_bp)
        kaynak = meta.get("investing_canli") or meta.get("investing_kapanis", "Investing.com")
        if manuel and abs(manuel - inv_bp) > fark_bp_esik:
            deger = float(max(inv_bp, manuel))
            uyari.append(
                f"Investing {inv_bp:.0f} vs yedek {manuel:.0f} bp — muhafazakâr **{deger:.0f}** bp."
            )
        if len(inv_vals) >= 2 and _rel_fark(inv_vals[0], inv_vals[1]) <= capraz:
            dogrulandi = True
            kaynak += " — Investing canlı/kapanış uyumlu"
        else:
            uyari.append(
                "Bloomberg Terminal erişilemedi — yalnızca Investing.com kullanılıyor. "
                "Terminal kurulumu için .env BLOOMBERG_* ayarlarına bakın."
            )
    elif manuel:
        deger = float(manuel)
        kaynak = meta.get("manual_yedek", "manual_inputs.json yedek")
        uyari.append("Canlı CDS API yok — manual_inputs otomatik yedek kullanıldı.")
    elif wgb:
        deger = float(wgb[0])
        kaynak = wgb[1]
        uyari.append("Bloomberg/Investing yok — WorldGovernmentBonds yedek.")
    else:
        onceki = _onceki_deger()
        if onceki:
            deger = float(onceki)
            kaynak = f"Önbellek ({onceki:.0f} bp) — canlı API yok"
            uyari.append("CDS API'lerine ulaşılamadı — son doğrulanmış değer.")
        else:
            deger, kaynak = _cds_piyasa_modeli(vix, siyasi)
            uyari.append("CDS piyasa modeli — gerçek kotasyon değil.")

    ham = inv_bp or bloomberg_bp or deger

    if savas >= config.SAVAS_RISK_ESIGI and deger is not None:
        taban = bloomberg_bp or _onceki_deger() or (max(kaynaklar.values()) if kaynaklar else 250.0)
        if deger < taban * 0.92:
            eski = deger
            deger = float(max(deger, taban))
            uyari.append(
                f"Jeopolitik haber yoğun ({savas}/48s) iken CDS **{eski:.0f}** bp düşük; "
                f"**{deger:.0f}** bp referansına yükseltildi."
            )
            kaynak += " · jeopolitik taban"

    assert deger is not None
    _cache_yaz(deger, kaynak.split("—")[0].strip())
    if dogrulandi or bloomberg_bp is not None or inv_bp is not None:
        _otomatik_referans_yaz(deger, kaynak)

    return CdsSonuc(
        deger=deger,
        kaynak=kaynak,
        ham=float(ham) if ham is not None else None,
        dogrulandi=dogrulandi,
        uyari=uyari,
        kaynaklar=kaynaklar,
    )
