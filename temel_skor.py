# -*- coding: utf-8 -*-
"""
Temel skor katmanı — değerleme, makro rejim uyumu, volatilite/profil, vade.
Teknik skor korunur; bileşik skor karar etiketlerini belirler.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

import config

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

from bist_52h_eur import degerleme_52h_pozisyon, format_52h_metin
import pandas as pd


def _degerleme_puan(zirve_52h_pct: Optional[float], max_puan: float) -> float:
    """52H bandı — dip 30p, zirve 0p, arası lineer."""
    if zirve_52h_pct is None:
        return max_puan * 0.5
    z = float(zirve_52h_pct)
    if z <= 30:
        return max_puan
    if z >= 70:
        return 0.0
    return max_puan * (70.0 - z) / 40.0


def _vol_30g_yillik(close: pd.Series) -> Optional[float]:
    close = close.dropna()
    if len(close) < 15:
        return None
    rets = close.pct_change().dropna().tail(30)
    if len(rets) < 10:
        return None
    return float(rets.std() * (252 ** 0.5) * 100)


def _vol_profil_puan(vol: Optional[float], profil_risk: str, max_puan: float = 25.0) -> float:
    if vol is None:
        return max_puan * 0.5
    limit = config.PROFIL_MAX_VOL_YILLIK.get(profil_risk, 32.0)
    if vol <= limit:
        return max_puan
    if vol >= limit * 1.5:
        return 0.0
    return max_puan * max(0.0, (limit * 1.5 - vol) / (limit * 0.5))


def _vade_uyum_puan(
    profil_vade: str,
    sektor: str,
    piyasa: str,
    max_puan: float = 15.0,
) -> Tuple[float, bool]:
    """ETF min ufuk kontrolü; False = zorunlu BEKLE."""
    from investor_profile import VADE_GUN

    if piyasa != "ETF":
        return max_puan, True

    min_gun = config.ETF_MIN_UFUK_GUN.get(sektor, 181)
    kullanici = VADE_GUN.get(profil_vade, 365)
    if kullanici >= min_gun:
        return max_puan, True
    if kullanici >= min_gun * 0.75:
        return max_puan * 0.4, False
    return 0.0, False


def _etf_makro_puan(rejim: str, sektor: str) -> float:
    kategori = config.ETF_SEKTOR_KATEGORI.get(sektor, "hisse_global")
    tablo = config.REJIM_ETF_KATEGORI_PUAN.get(rejim) or config.REJIM_ETF_KATEGORI_PUAN["NOTR"]
    return float(tablo.get(kategori, tablo.get("hisse_global", 15)))


def _hisse_makro_puan(rejim: str, sektor: str) -> float:
    grup = config.HISSE_SEKTOR_GRUBU.get(sektor, "dongusel")
    tablo = config.REJIM_HISSE_SEKTOR_PUAN.get(rejim) or config.REJIM_HISSE_SEKTOR_PUAN["NOTR"]
    return float(tablo.get(grup, 15))


def _momentum_puan(h: "HisseAnaliz", close: pd.Series, max_puan: float = 25.0) -> float:
    puan = 0.0
    y1 = getattr(h, "degisim_1y", None)
    if y1 is None and close is not None and len(close.dropna()) >= 2:
        from signal_engine.data.bars import pct_change_calendar

        y1 = pct_change_calendar(close, 365)
    if y1 is not None:
        if y1 >= config.AL_TEK_HISSE_Y1_MIN:
            puan += 15.0
        elif y1 >= config.AL_TEK_HISSE_Y1_IZLE:
            puan += 8.0
        elif y1 > 0:
            puan += 3.0
    elif h.degisim_3ay is not None and h.degisim_3ay > 0:
        puan += 6.0
    if h.degisim_3ay is not None and h.degisim_3ay > 0:
        puan += min(10.0, max(0.0, h.degisim_3ay / 2))
    return min(max_puan, puan)


def _peer_puan(h: "HisseAnaliz", max_puan: float = 20.0) -> float:
    peer = h.peer_yuzdelik
    if peer is None:
        return max_puan * 0.5
    return max(0.0, min(max_puan, float(peer) / 100.0 * max_puan))


def _temel_dusuren_faktorler(h: "HisseAnaliz", parcalar: dict) -> str:
    dusuk = []
    z52 = degerleme_52h_pozisyon(h)
    if parcalar.get("degerleme", 0) < 10 and z52 is not None and z52 >= 70:
        dusuk.append(f"{format_52h_metin(h)} (değerleme riski)")
    if parcalar.get("vade", 15) == 0:
        from investor_profile import VADE_GUN, VADE_SECENEKLERI

        min_g = config.ETF_MIN_UFUK_GUN.get(h.sektor, 181)
        dusuk.append(
            f"vade uyumsuz (min {min_g // 30} ay, profil {VADE_SECENEKLERI.get(h._profil_vade, h._profil_vade)})"
        )
    if parcalar.get("vol", 25) < 8:
        dusuk.append("volatilite profil üstü")
    if parcalar.get("makro", 15) < 10:
        dusuk.append("makro rejim uyumsuz")
    if parcalar.get("momentum", 0) == 0 and h.piyasa != "ETF":
        dusuk.append("momentum zayıf")
    if parcalar.get("peer", 10) < 8 and h.peer_yuzdelik is not None and h.peer_yuzdelik < 40:
        dusuk.append("sektör içi zayıf")
    if not dusuk:
        return ""
    return "Temel skor düşük: " + " + ".join(dusuk[:3])


def temel_skor_hesapla(
    h: "HisseAnaliz",
    makro_rejim: str,
    profil_vade: str,
    profil_risk: str,
    vol_30g: Optional[float] = None,
    close: Optional[pd.Series] = None,
) -> Tuple[float, float, bool, str, dict]:
    """
    Returns (temel_skor, vade_uyum_puani, vade_uygun, temel_not, parcalar).
    """
    h._profil_vade = profil_vade
    parcalar: dict = {}

    if h.piyasa == "EMTIA" or h.varlik_turu == "emtia":
        # Spot emtia: değerleme + vol; hisse peer/momentum yok
        parcalar["degerleme"] = _degerleme_puan(h.zirve_52h_pct, 35.0)
        parcalar["makro"] = _etf_makro_puan(makro_rejim, h.sektor if h.sektor in ("altin", "emtia") else "altin")
        parcalar["vol"] = _vol_profil_puan(vol_30g, profil_risk, 30.0)
        vade_p, vade_ok = 15.0, True
        parcalar["vade"] = vade_p
    elif h.piyasa == "ETF" or h.varlik_turu == "etf":
        parcalar["degerleme"] = _degerleme_puan(h.zirve_52h_pct, 30.0)
        parcalar["makro"] = _etf_makro_puan(makro_rejim, h.sektor)
        parcalar["vol"] = _vol_profil_puan(vol_30g, profil_risk, 25.0)
        vade_p, vade_ok = _vade_uyum_puan(profil_vade, h.sektor, "ETF", 15.0)
        parcalar["vade"] = vade_p
    else:
        parcalar["degerleme"] = _degerleme_puan(degerleme_52h_pozisyon(h), 25.0)
        parcalar["makro"] = _hisse_makro_puan(makro_rejim, h.sektor)
        parcalar["momentum"] = _momentum_puan(h, close if close is not None else pd.Series(dtype=float))
        parcalar["peer"] = _peer_puan(h, 20.0)
        vade_p, vade_ok = 15.0, True
        parcalar["vade"] = vade_p

    temel = sum(parcalar.values())
    temel = max(0.0, min(100.0, temel))
    notu = _temel_dusuren_faktorler(h, parcalar)
    return temel, vade_p, vade_ok, notu, parcalar


def bilesik_skor_hesapla(teknik: float, temel: float) -> float:
    w_t = config.BILESKE_TEKNIK_AGIRLIK
    w_f = config.BILESKE_TEMEL_AGIRLIK
    return max(0.0, min(100.0, teknik * w_t + temel * w_f))


def bilesik_etiket_kodu(bilesik: float, vade_uygun: bool) -> str:
    if not vade_uygun:
        return "IZLE"
    if bilesik >= config.BILESKE_AL_ESIK:
        return "UYGUN"
    if bilesik >= config.BILESKE_DIkkat_ESIK:
        return "SINIRLI"
    if bilesik >= config.BILESKE_BEKLE_ESIK:
        return "IZLE"
    return "UYGUN_DEGIL"


def _close_al(df: pd.DataFrame, sembol: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sembol in df.columns.get_level_values(0):
                obj = df[sembol]["Close"] if "Close" in df[sembol].columns else df[sembol].iloc[:, 0]
            else:
                return pd.Series(dtype=float)
        else:
            obj = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        if isinstance(obj, pd.DataFrame):
            obj = obj.iloc[:, 0]
        return obj.dropna()
    except Exception:
        return pd.Series(dtype=float)


def temel_skor_katmani_uygula(
    hisseler: List["HisseAnaliz"],
    df: pd.DataFrame,
    makro_rejim: str,
    profil,
) -> None:
    from investor_profile import YatirimProfili

    profil = profil or YatirimProfili()
    for h in hisseler:
        close = _close_al(df, h.sembol)
        vol = _vol_30g_yillik(close) if not close.empty else None
        h.vol_30g = vol

        temel, vade_p, vade_ok, notu, _ = temel_skor_hesapla(
            h, makro_rejim, profil.vade, profil.risk, vol_30g=vol, close=close,
        )
        teknik = float(h.teknik_skor or h.skor or 0)
        bilesik = bilesik_skor_hesapla(teknik, temel)

        h.temel_skor = round(temel, 1)
        h.bilesik_skor = round(bilesik, 1)
        h.vade_uyum_puani = vade_p
        h.vade_uygun = vade_ok
        h.temel_not = notu
        h.skor = h.bilesik_skor
