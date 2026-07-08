# -*- coding: utf-8 -*-
"""Streamlit cache_data — ağır veri çekimleri (app + önbellek)."""
from __future__ import annotations

import streamlit as st

from investor_profile import YatirimProfili, profil_mevduat_vadesi
from macro_data import canli_snapshot, demo_snapshot
from rates_tr import mevduat_analizi
from stock_scanner import tam_tarama
from backtest import backtest_calistir


@st.cache_data(ttl=300, show_spinner=False)
def cds_kaynak_ozet(_tick: int = 0):
    from cds_sync import cds_guncelleme_calistir
    return cds_guncelleme_calistir(taze=_tick > 0, tick=_tick)


@st.cache_data(ttl=180, show_spinner=False)
def veri_cek(canli: bool, _tick: int = 0):
    return canli_snapshot(taze=_tick > 0, _tick=_tick) if canli else demo_snapshot()


@st.cache_data(ttl=120, show_spinner=False)
def tarama_cek(
    canli: bool,
    rejim: str,
    snap_veri_kaynak: str,
    _tick: int = 0,
    haber_tara: bool = False,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
):
    del snap_veri_kaynak
    snap = veri_cek(canli, _tick)
    profil = YatirimProfili(risk=profil_risk, vade=profil_vade)
    return tam_tarama(
        makro_rejim=rejim, demo=not canli, snap=snap, haber_tara=haber_tara, profil=profil,
    )


@st.cache_data(ttl=600, show_spinner=False)
def mevduat_cek(enflasyon: float, profil_vade: str, eur_try: float, kalan_gun: int):
    return mevduat_analizi(
        enflasyon, profil_vade=profil_vade, eur_try=eur_try, kalan_gun=kalan_gun,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def backtest_veri(ay: int, vade: str, risk: str):
    return backtest_calistir(ay, profil=YatirimProfili(risk=risk, vade=vade))


@st.cache_data(ttl=3600, show_spinner=False)
def tefas_ham_cek(gun: int = 120, _tick: int = 0):
    from tefas_data import yk_fonlari_performans
    return yk_fonlari_performans(gun=gun, sadece_yk=True)


def veri_onbellegi_temizle() -> None:
    from cds_guven import cds_tick_onbellegi_temizle
    from macro_auto import enflasyon_cache_temizle
    from varlik_fiyat import fiyat_onbellegi_temizle

    cds_tick_onbellegi_temizle()
    enflasyon_cache_temizle()
    fiyat_onbellegi_temizle()
    veri_cek.clear()
    mevduat_cek.clear()
    tarama_cek.clear()
    backtest_veri.clear()
    tefas_ham_cek.clear()
    cds_kaynak_ozet.clear()
    try:
        from tefas_data import _BD_CACHE as tefas_bd_cache, _CACHE as tefas_py_cache
        tefas_py_cache["ts"] = 0.0
        tefas_bd_cache["ts"] = 0.0
        tefas_bd_cache["df"] = None
    except Exception:
        pass
