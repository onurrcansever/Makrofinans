# -*- coding: utf-8 -*-
"""
Streamlit cache_data + kalıcı disk önbelleği — ağır veri çekimleri.

Tarama/TEFAS: st.cache_data KULLANILMAZ — boş placeholder 30 dk kilitlenmesin diye.
Her çağrıda disk kontrol edilir; arka plan tamamlanınca bir sonraki okuma veriyi getirir.
"""
from __future__ import annotations

import streamlit as st

from disk_onbellek import TTL, disk_getir, disk_getir_aninda, disk_getir_swr, disk_hepsini_sil
from investor_profile import YatirimProfili, profil_mevduat_vadesi
from macro_data import canli_snapshot, demo_snapshot
from rates_tr import mevduat_analizi
from stock_scanner import tam_tarama
from backtest import backtest_calistir


def tarama_yukleniyor(tarama) -> bool:
    """Boş placeholder mı — arka plan henüz bitmedi mi?"""
    if tarama is None:
        return True
    if getattr(tarama, "hisseler", None) or getattr(tarama, "endeksler", None):
        return False
    return any("arka planda" in (u or "").lower() for u in (getattr(tarama, "uyarilar", None) or []))


def tefas_yukleniyor(sonuc) -> bool:
    if sonuc is None:
        return True
    if getattr(sonuc, "fonlar", None):
        return False
    hata = getattr(sonuc, "hata", "") or ""
    return "arka planda" in hata.lower()


@st.cache_data(ttl=TTL["cds"], show_spinner=False)
def cds_kaynak_ozet(_tick: int = 0):
    from cds_sync import cds_guncelleme_calistir
    return cds_guncelleme_calistir(taze=_tick > 0, tick=_tick)


@st.cache_data(ttl=TTL["makro"], show_spinner=False)
def veri_cek(canli: bool, _tick: int = 0):
    if not canli:
        return demo_snapshot()
    return disk_getir_swr(
        "makro:canli",
        TTL["makro"],
        lambda: canli_snapshot(taze=_tick > 0, _tick=_tick),
    )


def tarama_cek(
    canli: bool,
    rejim: str,
    snap_veri_kaynak: str,
    _tick: int = 0,
    haber_tara: bool = False,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
    *,
    zorla: bool = False,
    use_signal_v2: bool = True,
):
    """Hisse/endeks taraması — disk önbellek; zorla=True senkron çeker (Taramayı yenile)."""
    del snap_veri_kaynak
    from stock_scanner import TaramaSonucu

    anahtar = f"tarama:{canli}:{rejim}:{haber_tara}:{profil_risk}:{profil_vade}:v2={int(use_signal_v2)}:gbx_v3:live_v1"

    def _uret():
        snap = veri_cek(canli, _tick)
        profil = YatirimProfili(risk=profil_risk, vade=profil_vade)
        return tam_tarama(
            makro_rejim=rejim, demo=not canli, snap=snap, haber_tara=haber_tara,
            profil=profil, use_signal_v2=use_signal_v2,
        )

    def _placeholder():
        return TaramaSonucu(
            uyarilar=[
                "Hisse/endeks taraması arka planda yükleniyor — "
                "tablolar 30–90 sn içinde otomatik dolacak."
            ],
            makro_rejim=rejim,
        )

    if zorla:
        sonuc = disk_getir_swr(anahtar, TTL["tarama"], _uret, blokla=True)
        return sonuc if sonuc is not None else _placeholder()

    veri, yas = disk_getir(anahtar, TTL["tarama"], bayat_kabul=True)
    if veri is not None:
        if yas is not None and yas > TTL["tarama"]:
            disk_getir_aninda(anahtar, TTL["tarama"], _uret, varsayilan=veri)
        return veri

    disk_getir_aninda(anahtar, TTL["tarama"], _uret, varsayilan=None)
    return _placeholder()


@st.cache_data(ttl=TTL["mevduat"], show_spinner=False)
def mevduat_cek(enflasyon: float, profil_vade: str, eur_try: float, kalan_gun: int):
    return disk_getir_swr(
        f"mevduat:{round(enflasyon, 1)}:{profil_vade}:{kalan_gun}",
        TTL["mevduat"],
        lambda: mevduat_analizi(
            enflasyon, profil_vade=profil_vade, eur_try=eur_try, kalan_gun=kalan_gun,
        ),
    )


def backtest_veri(ay: int, vade: str, risk: str, *, zorla: bool = False):
    anahtar = f"backtest:{ay}:{vade}:{risk}"

    def _uret():
        return backtest_calistir(ay, profil=YatirimProfili(risk=risk, vade=vade))

    if zorla:
        return disk_getir_swr(anahtar, TTL["backtest"], _uret, blokla=True)

    veri, yas = disk_getir(anahtar, TTL["backtest"], bayat_kabul=True)
    if veri is not None:
        if yas is not None and yas > TTL["backtest"]:
            disk_getir_aninda(anahtar, TTL["backtest"], _uret, varsayilan=veri)
        return veri

    disk_getir_aninda(anahtar, TTL["backtest"], _uret, varsayilan=None)
    return {"hata": "Backtest arka planda yükleniyor — bir dakika sonra yenileyin."}


def tefas_ham_cek(gun: int = 120, _tick: int = 0, *, zorla: bool = False):
    from tefas_data import TefasTaramaSonuc, yk_fonlari_performans

    anahtar = f"tefas:{gun}"

    def _uret():
        sonuc = yk_fonlari_performans(gun=gun, sadece_yk=True)
        return None if getattr(sonuc, "hata", "") else sonuc

    def _placeholder():
        return TefasTaramaSonuc(
            hata="TEFAS arka planda yükleniyor — tablolar 30–90 sn içinde otomatik dolacak.",
            guncelleme="",
        )

    if zorla:
        sonuc = disk_getir_swr(anahtar, TTL["tefas"], _uret, blokla=True)
        return sonuc if sonuc is not None else _placeholder()

    veri, yas = disk_getir(anahtar, TTL["tefas"], bayat_kabul=True)
    if veri is not None:
        if yas is not None and yas > TTL["tefas"]:
            disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=veri)
        return veri

    disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=None)
    return _placeholder()


def veri_onbellegi_temizle() -> None:
    from cds_guven import cds_tick_onbellegi_temizle
    from macro_auto import enflasyon_cache_temizle
    from varlik_fiyat import fiyat_onbellegi_temizle
    from signal_engine.data.live_quote import clear_live_quote_cache
    from signal_engine.data.quote_normalize import fetch_source_quote_currency

    fetch_source_quote_currency.cache_clear()
    # Son kotasyonlar diskte kalsın — yenile bitene / yeni yazılana kadar 1G SWR
    clear_live_quote_cache(keep_disk=True)
    cds_tick_onbellegi_temizle()
    enflasyon_cache_temizle()
    fiyat_onbellegi_temizle()
    veri_cek.clear()
    mevduat_cek.clear()
    cds_kaynak_ozet.clear()
    disk_hepsini_sil()
    try:
        from tefas_data import _BD_CACHE as tefas_bd_cache, _CACHE as tefas_py_cache
        tefas_py_cache["ts"] = 0.0
        tefas_bd_cache["ts"] = 0.0
        tefas_bd_cache["df"] = None
    except Exception:
        pass
