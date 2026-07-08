# -*- coding: utf-8 -*-
"""Uygulama önbelleği — hızlı çekirdek + sayfa bazlı ağır yükleme."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Set

import streamlit as st

from advice_engine import DanismanRaporu
from allocation_engine import TahsisSonucu, tahsis_hesapla
from birlesik_oneri import BirlesikOneri, birlesik_oneri_olustur
from investor_profile import YatirimProfili, profil_mevduat_vadesi
from kullanici_portfoy import KullaniciPortfoy
from macro_data import MacroSnapshot
from tl_durum import TlDurumOzeti, tl_durum_olustur
from varlik_fiyat import PortfoyDeger, portfoy_degerle
from varliklarim import VarlikStore, yukle_store

from app_veri import (
    backtest_veri,
    cds_kaynak_ozet,
    mevduat_cek,
    tarama_cek,
    tefas_ham_cek,
    veri_cek,
)

SAYFA_TARAMA = frozenset({
    "Portföy Tahsisi",
    "AI Danışman",
    "Hisse & Endeks Taraması",
})
SAYFA_TEFAS = frozenset({"Portföy Tahsisi", "TEFAS Fonları"})
SAYFA_BIRLESIK = frozenset({"Portföy Tahsisi"})
SAYFA_DANISMAN_TAM = frozenset({"AI Danışman"})
SAYFA_BACKTEST = frozenset({"Backtest"})
SAYFA_VARLIK = frozenset({"Varlıklarım"})


@dataclass
class AppOnbellek:
    snap: MacroSnapshot
    tahsis: TahsisSonucu
    mevduat_ozet: Any
    danisman: DanismanRaporu
    tl_durum: TlDurumOzeti
    birlesik: BirlesikOneri
    varlik_store: VarlikStore
    cds_son: Any
    profil_mevduat_etiket: str
    profil_mevduat_gun: int
    yukleme_zamani: str
    tarama: Any = None
    tefas_ham: Any = None
    backtest: Any = None
    varlik_deger: Optional[PortfoyDeger] = None
    varlik_deger_portfoy_id: str = ""
    birlesik_tam: bool = False
    danisman_tam: bool = False
    yuklenen_sayfalar: Set[str] = field(default_factory=set)


def onbellek_anahtari(
    *,
    tick: int,
    profil_anahtar: str,
    kp: KullaniciPortfoy,
    canli_mod: bool,
    haber_tara: bool,
    bt_ay: int,
    mevduat_imza: str = "",
) -> str:
    return (
        f"{tick}|{profil_anahtar}|{kp.para_birimi}|{int(kp.toplam)}|"
        f"{canli_mod}|{haber_tara}|{bt_ay}|{mevduat_imza}"
    )


def _mevduat_imza(kp: KullaniciPortfoy) -> str:
    parcalar = [f"{p.tur}:{int(p.tutar)}:{p.fon_kodu or ''}" for p in kp.pozisyonlar]
    return "|".join(parcalar) if parcalar else "bos"


def onbellek_gecersiz_kil() -> None:
    st.session_state.pop("app_onbellek", None)
    st.session_state.pop("app_onbellek_key", None)
    st.session_state.pop("birlesik_oneri", None)
    st.session_state.pop("_birlesik_ck", None)
    st.session_state.pop("_varlik_deger_cache", None)
    st.session_state.tarama_son = None


def _tarama_yukle(
    ob: AppOnbellek,
    *,
    canli_mod: bool,
    tick: int,
    profil: YatirimProfili,
    haber_tara: bool,
) -> None:
    if ob.tarama is not None:
        return
    ob.tarama = tarama_cek(
        canli_mod,
        ob.tahsis.rejim.rejim,
        ob.snap.veri_kaynak,
        tick,
        haber_tara=haber_tara,
        profil_risk=profil.risk,
        profil_vade=profil.vade,
    )
    st.session_state.tarama_son = ob.tarama


def _tefas_yukle(ob: AppOnbellek, *, tick: int) -> None:
    if ob.tefas_ham is not None and not getattr(ob.tefas_ham, "hata", ""):
        return
    ob.tefas_ham = tefas_ham_cek(120, tick)


def _birlesik_guncelle(
    ob: AppOnbellek,
    *,
    profil: YatirimProfili,
    kp: KullaniciPortfoy,
    tam: bool,
) -> None:
    ob.birlesik = birlesik_oneri_olustur(
        ob.snap,
        ob.tahsis,
        profil,
        kp,
        mevduat_reel=getattr(ob.mevduat_ozet, "profil_vade_reel", None),
        tarama=ob.tarama if tam else None,
        tefas_ham=ob.tefas_ham if tam else None,
        tefas_istek=tam,
        varlik_store=ob.varlik_store,
    )
    ob.birlesik_tam = tam


def _danisman_guncelle(ob: AppOnbellek, *, profil: YatirimProfili, tam: bool) -> None:
    from advice_engine import danisman_raporu_olustur

    ob.danisman = danisman_raporu_olustur(
        ob.snap,
        ob.tahsis,
        profil,
        ob.tarama if tam else None,
        mevduat=ob.mevduat_ozet,
    )
    ob.danisman_tam = tam


def _varlik_deger_yukle(ob: AppOnbellek, *, tick: int) -> None:
    aktif = ob.varlik_store.aktif()
    if not aktif or not aktif.pozisyonlar:
        ob.varlik_deger = None
        ob.varlik_deger_portfoy_id = ""
        return
    if ob.varlik_deger is not None and ob.varlik_deger_portfoy_id == aktif.id:
        return
    ob.varlik_deger = portfoy_degerle(aktif, ob.snap, cache_salt=str(tick))
    ob.varlik_deger_portfoy_id = aktif.id


def onbellek_sayfa_hazirla(
    ob: AppOnbellek,
    sayfa: str,
    *,
    canli_mod: bool,
    tick: int,
    profil: YatirimProfili,
    kp: KullaniciPortfoy,
    haber_tara: bool,
    bt_ay: int,
) -> AppOnbellek:
    """İlgili sekme için ağır veriyi yükler (önceden yüklenmediyse)."""
    if sayfa in ob.yuklenen_sayfalar:
        return ob

    need_tarama = sayfa in SAYFA_TARAMA
    need_tefas = sayfa in SAYFA_TEFAS
    need_birlesik = sayfa in SAYFA_BIRLESIK
    need_danisman = sayfa in SAYFA_DANISMAN_TAM
    need_backtest = sayfa in SAYFA_BACKTEST
    need_varlik = sayfa in SAYFA_VARLIK

    if not any((need_tarama, need_tefas, need_backtest, need_varlik, need_birlesik, need_danisman)):
        ob.yuklenen_sayfalar.add(sayfa)
        return ob

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_tarama = None
        fut_tefas = None
        if need_tarama and ob.tarama is None:
            fut_tarama = ex.submit(
                _tarama_yukle,
                ob,
                canli_mod=canli_mod,
                tick=tick,
                profil=profil,
                haber_tara=haber_tara,
            )
        if need_tefas and (ob.tefas_ham is None or getattr(ob.tefas_ham, "hata", "")):
            fut_tefas = ex.submit(_tefas_yukle, ob, tick=tick)
        if fut_tarama:
            fut_tarama.result()
        if fut_tefas:
            fut_tefas.result()

    if need_backtest and ob.backtest is None:
        ob.backtest = backtest_veri(bt_ay, profil.vade, profil.risk)

    if need_varlik:
        _varlik_deger_yukle(ob, tick=tick)

    if need_birlesik:
        _birlesik_guncelle(ob, profil=profil, kp=kp, tam=True)
        st.session_state.birlesik_oneri = ob.birlesik
        st.session_state._birlesik_ck = st.session_state.get("app_onbellek_key")

    if need_danisman:
        _danisman_guncelle(ob, profil=profil, tam=True)

    ob.yuklenen_sayfalar.add(sayfa)
    st.session_state.app_onbellek = ob
    return ob


def uygulama_onbellegi_al(
    *,
    canli_mod: bool,
    tick: int,
    profil: YatirimProfili,
    profil_anahtar: str,
    kp: KullaniciPortfoy,
    haber_tara: bool,
    bt_ay: int,
) -> AppOnbellek:
    key = onbellek_anahtari(
        tick=tick,
        profil_anahtar=profil_anahtar,
        kp=kp,
        canli_mod=canli_mod,
        haber_tara=haber_tara,
        bt_ay=bt_ay,
        mevduat_imza=_mevduat_imza(kp),
    )
    cached = st.session_state.get("app_onbellek")
    if cached and st.session_state.get("app_onbellek_key") == key:
        return cached

    adimlar = [
        "CDS ve makro veriler",
        "Portföy tahsisi ve mevduat faizleri",
        "TL kararı ve makro özet",
    ]
    progress = st.progress(0.0, text="Temel veriler hazırlanıyor…")

    def _ilerle(i: int) -> None:
        progress.progress(
            (i + 1) / len(adimlar),
            text=f"{adimlar[i]}… ({i + 1}/{len(adimlar)})",
        )

    _ilerle(0)
    cds_son = cds_kaynak_ozet(tick)
    st.session_state["cds_son_kaynak"] = cds_son
    snap = veri_cek(canli_mod, tick)

    _ilerle(1)
    tahsis = tahsis_hesapla(snap, profil)
    profil_mevduat_etiket, profil_mevduat_gun = profil_mevduat_vadesi(profil)
    mevduat_ozet = mevduat_cek(
        snap.enflasyon_tr_yillik or 35.0,
        profil_mevduat_etiket,
        snap.veri.eur_try or 35.0,
        profil_mevduat_gun,
    )

    _ilerle(2)
    tl_durum = tl_durum_olustur(snap, tahsis, mevduat_ozet)
    if "varlik_store" not in st.session_state:
        st.session_state.varlik_store = yukle_store()
    varlik_store: VarlikStore = st.session_state.varlik_store

    ob = AppOnbellek(
        snap=snap,
        tahsis=tahsis,
        mevduat_ozet=mevduat_ozet,
        tarama=None,
        danisman=DanismanRaporu(genel_ozet="", rejim_yorumu="", oncelik_sirasi=[]),
        tl_durum=tl_durum,
        birlesik=BirlesikOneri(),
        tefas_ham=None,
        backtest=None,
        varlik_store=varlik_store,
        varlik_deger=None,
        varlik_deger_portfoy_id="",
        cds_son=cds_son,
        profil_mevduat_etiket=profil_mevduat_etiket,
        profil_mevduat_gun=profil_mevduat_gun,
        yukleme_zamani=datetime.now().strftime("%H:%M:%S"),
    )
    _danisman_guncelle(ob, profil=profil, tam=False)
    _birlesik_guncelle(ob, profil=profil, kp=kp, tam=False)
    st.session_state.birlesik_oneri = ob.birlesik
    st.session_state._birlesik_ck = key

    progress.progress(1.0, text="Temel veriler hazır — ağır bölümler sekmede yüklenir")
    progress.empty()

    st.session_state.app_onbellek = ob
    st.session_state.app_onbellek_key = key
    return ob
