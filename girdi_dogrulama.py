# -*- coding: utf-8 -*-
"""
Girdi doğrulama — sanity band, sıçrama koruması, onay bekliyor durumu.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config
from db_paths import market_cache_db

KRITIK_GOSTERGELER = ("cds", "enflasyon", "tcmb_faizi", "eur_try", "altin_usd")


def _onay_path() -> str:
    return os.getenv("GIRDI_ONAY_STATE_PATH", config.GIRDI_ONAY_STATE_PATH)


@dataclass
class GostergeSonuc:
    anahtar: str
    deger: Optional[float]
    durum: str  # OK | SUPHELI | ONAY_BEKLIYOR
    uyari: Optional[str] = None
    onceki: Optional[float] = None
    rejim_icin_deger: Optional[float] = None


@dataclass
class GirdiDogrulamaSonucu:
    gostergeler: Dict[str, GostergeSonuc] = field(default_factory=dict)
    uyarilar: List[str] = field(default_factory=list)
    rejim_donduruldu: bool = False
    onay_bekleyen: List[str] = field(default_factory=list)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(market_cache_db())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gosterge_gecmisi (
            anahtar TEXT NOT NULL,
            ts REAL NOT NULL,
            deger REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gosterge_anahtar_ts ON gosterge_gecmisi (anahtar, ts)"
    )
    return conn


def gosterge_kaydet(anahtar: str, deger: float) -> None:
    if deger is None:
        return
    try:
        conn = _conn()
        conn.execute(
            "INSERT INTO gosterge_gecmisi (anahtar, ts, deger) VALUES (?, ?, ?)",
            (anahtar, time.time(), float(deger)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _gecmis_band(anahtar: str) -> Optional[Tuple[float, float]]:
    """Son N günlük min-max + tolerans."""
    try:
        conn = _conn()
        kesim = time.time() - config.SANITY_BAND_GUN * 86400
        rows = conn.execute(
            "SELECT deger FROM gosterge_gecmisi WHERE anahtar=? AND ts>=?",
            (anahtar, kesim),
        ).fetchall()
        conn.close()
        if len(rows) < 3:
            return None
        vals = [float(r[0]) for r in rows]
        lo, hi = min(vals), max(vals)
        tol = config.SANITY_BAND_TOLERANS
        return lo * (1 - tol), hi * (1 + tol)
    except Exception:
        return None


def _onceki_deger(anahtar: str) -> Optional[float]:
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT deger FROM gosterge_gecmisi WHERE anahtar=? ORDER BY ts DESC LIMIT 1",
            (anahtar,),
        ).fetchone()
        conn.close()
        if row:
            return float(row[0])
    except Exception:
        pass
    return None


def _onay_oku() -> dict:
    if not os.path.isfile(_onay_path()):
        return {"pending": {}}
    try:
        with open(_onay_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pending": {}}


def _onay_yaz(state: dict) -> None:
    with open(_onay_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _sicrama_mi(anahtar: str, yeni: float, onceki: float) -> bool:
    if onceki <= 0:
        return False
    if anahtar == "cds":
        if abs(yeni - onceki) >= config.CDS_SICRAMA_BP:
            return True
    rel = abs(yeni - onceki) / onceki
    return rel > config.GIRDI_SICRAMA_YUZDE


def _onay_isle(anahtar: str, yeni: float, onceki: Optional[float]) -> Tuple[str, float, Optional[str]]:
    """
    Returns (durum, rejim_icin_deger, uyari).
    ONAY_BEKLIYOR: rejim için önceki değer kullanılır.
    """
    state = _onay_oku()
    pending = state.get("pending", {})
    mevcut = pending.get(anahtar)

    if mevcut and abs(float(mevcut["deger"]) - yeni) < 0.01:
        del pending[anahtar]
        state["pending"] = pending
        _onay_yaz(state)
        return (
            "OK",
            yeni,
            f"{anahtar.upper()} sıçraması teyit edildi: **{mevcut.get('onceki', onceki):.2f}** → **{yeni:.2f}** "
            f"(2. ardışık çalıştırma).",
        )

    if onceki is None or not _sicrama_mi(anahtar, yeni, onceki):
        if anahtar in pending:
            del pending[anahtar]
            state["pending"] = pending
            _onay_yaz(state)
        return "OK", yeni, None

    pending[anahtar] = {
        "deger": yeni,
        "onceki": onceki,
        "ts": time.time(),
    }
    state["pending"] = pending
    _onay_yaz(state)
    uyari = (
        f"Girdi sıçraması — **{anahtar}** {onceki:.2f} → {yeni:.2f}: "
        f"onay bekliyor; rejim donduruldu (önceki değer rejimde kullanılıyor)."
    )
    return "ONAY_BEKLIYOR", onceki, uyari


def gosterge_kontrol(anahtar: str, deger: Optional[float]) -> GostergeSonuc:
    if deger is None:
        return GostergeSonuc(anahtar=anahtar, deger=None, durum="OK")

    onceki = _onceki_deger(anahtar)
    durum = "OK"
    uyari = None
    rejim_icin = deger

    band = _gecmis_band(anahtar)
    if band and (deger < band[0] or deger > band[1]):
        durum = "SUPHELI"
        uyari = (
            f"**{anahtar.upper()}** SUPHELI: {deger:.2f} son {config.SANITY_BAND_GUN}g "
            f"bandının ({band[0]:.2f}–{band[1]:.2f}) dışında."
        )

    onay_durum, rejim_deger, onay_uyari = _onay_isle(anahtar, deger, onceki)
    if onay_durum == "ONAY_BEKLIYOR":
        durum = "ONAY_BEKLIYOR"
        rejim_icin = rejim_deger
        uyari = (uyari + " " + onay_uyari) if uyari else onay_uyari
    elif onay_uyari:
        uyari = (uyari + " " + onay_uyari) if uyari else onay_uyari

    gosterge_kaydet(anahtar, deger)
    return GostergeSonuc(
        anahtar=anahtar,
        deger=deger,
        durum=durum,
        uyari=uyari,
        onceki=onceki,
        rejim_icin_deger=rejim_icin,
    )


def girdi_dogrulama_uygula(
    degerler: Dict[str, Optional[float]],
) -> GirdiDogrulamaSonucu:
    """Kritik göstergeleri doğrula; rejim dondurma bayrağını üret."""
    sonuc = GirdiDogrulamaSonucu()
    for anahtar in KRITIK_GOSTERGELER:
        if anahtar not in degerler:
            continue
        gs = gosterge_kontrol(anahtar, degerler[anahtar])
        sonuc.gostergeler[anahtar] = gs
        if gs.uyari:
            sonuc.uyarilar.append(gs.uyari)
        if gs.durum == "ONAY_BEKLIYOR":
            sonuc.onay_bekleyen.append(anahtar)
            sonuc.rejim_donduruldu = True
    return sonuc


def rejim_icin_degerler(gd: GirdiDogrulamaSonucu) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, gs in gd.gostergeler.items():
        if gs.rejim_icin_deger is not None:
            out[k] = gs.rejim_icin_deger
    return out


def girdi_rapor_uyarilari(snap) -> List[str]:
    """PDF/HTML için girdi doğrulama uyarıları (CDS sıçrama, onay bekliyor)."""
    satirlar: List[str] = []
    gd = getattr(snap, "girdi_dogrulama", None)
    if not gd:
        return satirlar
    if gd.rejim_donduruldu:
        bekleyen = ", ".join(gd.onay_bekleyen) or "—"
        satirlar.append(
            f"Girdi sıçraması — makro rejim donduruldu (onay bekleyen: {bekleyen}). "
            f"İkinci ardışık okumada teyit edilir."
        )
    for gs in gd.gostergeler.values():
        if gs.uyari and gs.durum in ("ONAY_BEKLIYOR", "SUPHELI"):
            satirlar.append(gs.uyari.replace("**", ""))
    return satirlar


def snap_rejim_icin(snap):
    """Rejim hesabı için onay bekleyen girdilerde önceki değerleri uygula."""
    from copy import deepcopy

    gd = getattr(snap, "girdi_dogrulama", None)
    if not gd:
        return snap
    s = deepcopy(snap)
    gs_cds = gd.gostergeler.get("cds")
    if gs_cds and gs_cds.rejim_icin_deger is not None:
        s.veri.cds_5y_bp = gs_cds.rejim_icin_deger
    gs_tcmb = gd.gostergeler.get("tcmb_faizi")
    if gs_tcmb and gs_tcmb.rejim_icin_deger is not None:
        s.veri.tcmb_politika_faizi = gs_tcmb.rejim_icin_deger
    gs_enf = gd.gostergeler.get("enflasyon")
    if gs_enf and gs_enf.rejim_icin_deger is not None:
        s.enflasyon_tr_yillik = gs_enf.rejim_icin_deger
    return s
