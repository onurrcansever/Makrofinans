# -*- coding: utf-8 -*-
"""Favorilerim — Streamlit paneli ve hızlı ekleme bileşenleri."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from app_veri import tarama_yukleniyor, tefas_yukleniyor
from fiyat_para import (
    fiyat_al_display_cross_warning,
    fiyat_sutun_adi,
    getiri_sutun_adi,
    session_gosterim_pb,
    tablo_fiyat,
    tablo_fx_hazirla,
    tablo_getiri,
    tefas_tablo_fiyat,
    spot_fiyat_veya_live,
)
from tefas_universe import tefas_fiyat_kaynak_pb
from favoriler import (
    TUR_ETIKET,
    FavoriItem,
    FavoriStore,
    _uid,
    favori_ekle,
    favori_sil,
    favori_var,
    normalize_sembol,
    tur_etiket,
    yukle_store as yukle_favori_store,
)
from favoriler_widgets import (
    favori_store_yenile,
    favori_yildiz_metni,
    pop_pending_favori_action,
    queue_favori_action,
    render_df_table_with_star_buttons,
)
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from portfoy_yoneticisi import yonetici_tablo_kolonlari
from stock_scanner import SINYAL_ETIKET
from ui_regime_badge import regime_badge_html
from ui_theme import render_metric_strip
from varlik_fiyat import _yf_indir
from varliklarim import VarlikPozisyon, VarlikStore, pozisyon_ekle, yukle_store as yukle_varlik_store


def _tarama_hisse(tarama, sembol: str):
    if not tarama or tarama_yukleniyor(tarama):
        return None
    hedef = (sembol or "").upper().strip()
    hedef_kok = hedef.split(".")[0]
    for h in tarama.hisseler:
        hs = (h.sembol or "").upper()
        if hs == hedef or hs.split(".")[0] == hedef_kok:
            return h
        rt = (getattr(h, "revolut_ticker", "") or "").upper()
        if rt and (hedef.startswith(rt) or hedef_kok == rt.split(".")[0]):
            return h
    return None


def _tarama_endeks(tarama, sembol: str):
    if not tarama or tarama_yukleniyor(tarama):
        return None
    hedef = sembol.upper()
    for e in tarama.endeksler:
        if e.sembol.upper() == hedef:
            return e
    return None


def _tefas_skorlu(
    tefas_ham,
    profil: YatirimProfili,
    rejim: str,
    *,
    gosterim_pb: str,
    eur_s,
    usd_s,
):
    if not tefas_ham or tefas_yukleniyor(tefas_ham) or getattr(tefas_ham, "hata", ""):
        return None
    if eur_s is None or usd_s is None or getattr(eur_s, "empty", True) or getattr(usd_s, "empty", True):
        return None
    from tefas_skor import fonlari_skorla

    return fonlari_skorla(
        tefas_ham, profil, rejim=rejim,
        gosterim_pb=gosterim_pb, eur_seri=eur_s, usd_seri=usd_s,
    )


def _guvenli_tablo_getiri(
    r_native_pct,
    gpb: str,
    gun: int,
    eur_s,
    usd_s,
    *,
    gbp_s=None,
    **kwargs,
):
    if eur_s is None or usd_s is None:
        return None
    if getattr(eur_s, "empty", True) or getattr(usd_s, "empty", True):
        return None
    try:
        return tablo_getiri(
            r_native_pct, gpb, gun, eur_s, usd_s, gbp_seri=gbp_s, **kwargs,
        )
    except Exception:
        return None


def _tefas_fon(tefas_sonuc, kod: str, tefas_ham=None):
    if not tefas_sonuc and not tefas_ham:
        return None
    hedef = kod.upper()
    for kaynak in (tefas_sonuc, tefas_ham):
        if not kaynak:
            continue
        for f in kaynak.fonlar:
            if f.kod.upper() == hedef:
                return f
    return None


def _yf_getiri(sembol: str, gun: int) -> Optional[float]:
    df = _yf_indir([sembol], period="6mo")
    if df is None or df.empty or sembol not in df.columns:
        return None
    seri = df[sembol].dropna()
    if len(seri) < 2:
        return None
    if len(seri) <= gun:
        return float((seri.iloc[-1] / seri.iloc[0] - 1) * 100)
    return float((seri.iloc[-1] / seri.iloc[-1 - gun] - 1) * 100)


def _tefas_yonetici_kolonlari(f, rejim: str) -> dict:
    emir_map = {"AL": "Al", "IZLE": "İzle", "BEKLE": "Bekle", "ZAYIF": "Uzak"}
    emir = emir_map.get(getattr(f, "oneri", "") or "", getattr(f, "oneri", "") or "—")
    return {
        "Emir": emir,
        "Al": "—",
        "Rejim": regime_badge_html(rejim or "NOTR", "", duration_days=None, fresh_change=False),
        "Veri": "TEFAS ✓",
    }


def _satir_doldur(
    item: FavoriItem,
    snap: MacroSnapshot,
    *,
    tarama=None,
    tefas_sonuc=None,
    tefas_ham=None,
    rejim: str = "NOTR",
    gpb: str,
    fx,
    eur_s,
    usd_s,
    gbp_s=None,
) -> dict:
    fiyat_kol = fiyat_sutun_adi(gpb)
    g1a = getiri_sutun_adi("1A", gpb)
    g3a = getiri_sutun_adi("3A", gpb)
    bos = {
        "Tür": tur_etiket(item.tur, item.sembol),
        "Sembol": item.sembol,
        "Ad": (item.ad or item.sembol)[:32],
        fiyat_kol: "—",
        g1a: None,
        g3a: None,
        "Sinyal / Öneri": "—",
        "Skor": "—",
        "Al": "—",
        "Rejim": "—",
        "Veri": "—",
    }

    if item.tur == "tefas":
        f = _tefas_fon(tefas_sonuc, item.sembol, tefas_ham=tefas_ham)
        if not f:
            return {**bos, "Veri": "TEFAS'ta bulunamadı"}
        bd = usd_s.index if usd_s is not None and not usd_s.empty else None
        src_pb = tefas_fiyat_kaynak_pb(f.para_birimi)
        fiyat_val = tefas_tablo_fiyat(
            f.fiyat, gpb, f.para_birimi, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd, chf_usd=getattr(fx, "chf_usd", None),
        )
        veri = "—"
        if src_pb is None:
            veri = "PB belirsiz — fiyat çevrilmedi"
        asset_pb = src_pb or "TL"
        return {
            **bos,
            "Ad": (f.kisa_ad or item.ad or f.kod)[:32],
            fiyat_kol: fiyat_val if fiyat_val is not None else "—",
            g1a: _guvenli_tablo_getiri(
                f.getiri_1a, gpb, 30, eur_s, usd_s, gbp_s=gbp_s, asset_pb=asset_pb, bar_dates=bd,
            ),
            g3a: _guvenli_tablo_getiri(
                f.getiri_3a, gpb, 90, eur_s, usd_s, gbp_s=gbp_s, asset_pb=asset_pb, bar_dates=bd,
            ),
            "Sinyal / Öneri": (f.oneri or "—").replace("IZLE", "İZLE").replace("ZAYIF", "Zayıf"),
            "Skor": f"{f.skor:.0f}" if f.skor else "—",
            "Veri": veri,
            **_tefas_yonetici_kolonlari(f, rejim),
        }

    if item.tur == "endeks":
        e = _tarama_endeks(tarama, item.sembol)
        if e:
            from endeks_yonlendirme import endeks_alanlarini_doldur, ozet_neden

            endeks_alanlarini_doldur([e], fx_ok=True)
            return {
                **bos,
                "Ad": (e.ad or item.ad)[:32],
            fiyat_kol: tablo_fiyat(
                e.fiyat, gpb, fx.eur_try, fx.usd_try, sembol=e.sembol,
                quote_currency=getattr(e, "quote_currency", ""),
                gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd, chf_usd=getattr(fx, "chf_usd", None),
            ),
                g1a: _guvenli_tablo_getiri(
                    e.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_s=gbp_s, sembol=e.sembol,
                    bar_dates=getattr(e, "close_bar_dates", None),
                ),
                g3a: _guvenli_tablo_getiri(
                    e.degisim_3ay, gpb, 63, eur_s, usd_s, gbp_s=gbp_s, sembol=e.sembol,
                    bar_dates=getattr(e, "close_bar_dates", None),
                ),
                "Sinyal / Öneri": (
                    f"{getattr(e, 'aksiyon_etiket', None) or 'Bekle'} — {ozet_neden(e)}"
                ),
                "Skor": (
                    f"{int(getattr(e, 'guven', 0) or 0)}"
                    if getattr(e, "guven", None) is not None
                    else (f"{e.skor:.0f}" if e.skor else "—")
                ),
            }
        g1 = _yf_getiri(item.sembol, 21)
        g3 = _yf_getiri(item.sembol, 63)
        return {**bos, g1a: g1, g3a: g3}

    h = _tarama_hisse(tarama, item.sembol)
    if h:
        vt = getattr(h, "varlik_turu", "hisse")
        px, qc = spot_fiyat_veya_live(
            h.sembol, getattr(h, "fiyat", None), getattr(h, "quote_currency", "") or "",
        )
        try:
            fiyat_val = tablo_fiyat(
                px, gpb, fx.eur_try, fx.usd_try,
                sembol=h.sembol, piyasa=h.piyasa, varlik_turu=vt,
                quote_currency=qc,
                gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd, chf_usd=getattr(fx, "chf_usd", None),
            )
        except Exception:
            fiyat_val = None
        yonetici = yonetici_tablo_kolonlari(h, gpb, fx)
        veri = yonetici.get("Veri", "—")
        if getattr(h, "veri_quarantine", False):
            veri = getattr(h, "veri_hatasi", "VERİ HATASI")[:40]
        cross = fiyat_al_display_cross_warning(fiyat_val, yonetici.get("Al", "—"))
        if cross:
            veri = cross[:40]
        return {
            **bos,
            "Ad": (h.ad or item.ad)[:32],
            fiyat_kol: fiyat_val,
            g1a: _guvenli_tablo_getiri(
                h.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_s=gbp_s,
                sembol=h.sembol, piyasa=h.piyasa, varlik_turu=vt,
                bar_dates=getattr(h, "close_bar_dates", None),
            ),
            g3a: _guvenli_tablo_getiri(
                h.degisim_3ay, gpb, 63, eur_s, usd_s, gbp_s=gbp_s,
                sembol=h.sembol, piyasa=h.piyasa, varlik_turu=vt,
                bar_dates=getattr(h, "close_bar_dates", None),
            ),
            "Sinyal / Öneri": getattr(h, "alim_uygun_etiket", None) or SINYAL_ETIKET.get(h.sinyal, h.sinyal),
            "Skor": f"{getattr(h, 'signal_v2_score', None) or h.skor:.0f}",
            **yonetici,
            "Veri": veri,
        }

    g1 = _yf_getiri(item.sembol, 21)
    g3 = _yf_getiri(item.sembol, 63)
    return {**bos, g1a: g1, g3a: g3}


def _portfoye_ekle_form(store_fav: FavoriStore, item: FavoriItem) -> None:
    if "varlik_store" not in st.session_state:
        st.session_state.varlik_store = yukle_varlik_store()
    vstore: VarlikStore = st.session_state.varlik_store
    aktif = vstore.aktif()
    if not aktif:
        st.warning("Önce Varlıklarım'da bir portföy oluşturun.")
        return

    tur_map = {"hisse": "hisse", "etf": "etf", "tefas": "tefas"}
    poz_tur = tur_map.get(item.tur)
    if not poz_tur:
        st.info("Endeks favorileri portföye eklenemez — hisse, ETF veya TEFAS seçin.")
        return

    with st.form(f"pf_ekle_{item.id}"):
        st.caption(f"**{item.sembol}** → portföy: **{aktif.ad}**")
        miktar = st.number_input("Miktar (adet/lot/pay)", min_value=0.0, step=1.0, value=0.0)
        alim = st.number_input("Alış fiyatı (birim, isteğe bağlı)", min_value=0.0, step=0.01, value=0.0)
        if st.form_submit_button("Portföye ekle"):
            if miktar <= 0:
                st.warning("Miktar girin.")
            else:
                maliyet = miktar * alim if alim > 0 else 0.0
                pozisyon_ekle(
                    vstore,
                    aktif.id,
                    VarlikPozisyon(
                        id=_uid(),
                        tur=poz_tur,
                        sembol=item.sembol,
                        ad=item.ad,
                        miktar=miktar,
                        maliyet=maliyet,
                        alim_fiyati=alim,
                        para_birimi="TL" if poz_tur == "tefas" else "EUR",
                        alim_tarihi=pd.Timestamp.now().date().isoformat(),
                    ),
                )
                st.session_state.varlik_store = vstore
                st.success(f"{item.sembol} portföye eklendi — **Varlıklarım**'dan düzenleyin.")


@st.dialog("İzleme listesi — işlem", width="large")
def _fav_islem_dialog(item_id: str) -> None:
    store = _store()
    item = next((x for x in store.items if x.id == item_id), None)
    if not item:
        st.warning("Kayıt bulunamadı.")
        return
    st.markdown(f"**{item.sembol}** · {tur_etiket(item.tur, item.sembol)}")
    st.caption(item.ad or item.sembol)

    if item.tur in ("hisse", "etf", "tefas"):
        st.markdown("##### Portföye ekle")
        _portfoye_ekle_form(store, item)
    else:
        st.info("Endeks kayıtları portföye eklenemez.")

    st.markdown("---")
    if st.button("Listeden çıkar", type="primary", use_container_width=True, key=f"fav_rm_{item_id}"):
        favori_sil(store, item_id)
        st.session_state.favori_store = store
        st.toast(f"{item.sembol.split('.')[0]} listeden çıkarıldı")
        st.rerun()


@st.fragment
def _favori_izleme_fragment(
    snap: MacroSnapshot,
    *,
    tarama=None,
    tefas_sonuc=None,
    tefas_ham=None,
    rejim: str = "NOTR",
    gpb: str = "EUR",
    fx=None,
    eur_s=None,
    usd_s=None,
    gbp_s=None,
) -> None:
    """İzleme listesi — her yıldız tıklamasında diskten yeniden kur (aynı store)."""
    store = favori_store_yenile()
    if not store.items:
        st.info("Liste boş — Hisse & ETF tablosundan ★ ekleyin.")
        return

    render_metric_strip([
        {"label": "Toplam", "value": str(len(store.items))},
        {"label": "Hisse", "value": str(sum(1 for x in store.items if x.tur == "hisse"))},
        {"label": "ETF", "value": str(sum(1 for x in store.items if x.tur == "etf"))},
        {"label": "TEFAS", "value": str(sum(1 for x in store.items if x.tur == "tefas"))},
    ])

    rows = []
    fav_meta = []
    for item in store.items:
        row = _satir_doldur(
            item, snap, tarama=tarama, tefas_sonuc=tefas_sonuc, tefas_ham=tefas_ham,
            rejim=rejim, gpb=gpb, fx=fx, eur_s=eur_s, usd_s=usd_s, gbp_s=gbp_s,
        )
        row = {"⭐": favori_yildiz_metni(item.tur, item.sembol), **row}
        rows.append(row)
        fav_meta.append((item.tur, item.sembol, item.ad or item.sembol))
    df = pd.DataFrame(rows)
    for col in df.columns:
        if " %" in col or col.endswith("%)"):
            df[col] = df[col].apply(
                lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) and pd.notna(v)
                else (v if v is not None else "—")
            )

    render_df_table_with_star_buttons(
        df,
        fav_meta,
        key_prefix="fav_izleme",
        max_height=420,
        row_ids=[item.id for item in store.items],
        action_col=True,
        on_action=queue_favori_action,
        badge_col="Sinyal / Öneri",
    )
    st.caption(
        f"Fiyat/getiri birimi: **{gpb}** (sidebar) · ★/☆ satır içi favori · "
        "**⋯** ile portföye ekleme / silme"
    )


def favoriler_paneli(
    snap: MacroSnapshot,
    *,
    tarama=None,
    tefas_ham=None,
    profil: Optional[YatirimProfili] = None,
    rejim: str = "NOTR",
) -> None:
    pending = pop_pending_favori_action()
    if pending:
        _fav_islem_dialog(pending)

    from ui_theme import render_page_header

    render_page_header("Favorilerim", "İzleme listesi — portföy değil")

    store = favori_store_yenile()
    gpb = session_gosterim_pb()
    try:
        fx, eur_s, usd_s, gbp_s, _ = tablo_fx_hazirla(snap, tarama)
    except Exception as exc:
        st.error(f"FX kurları yüklenemedi — fiyat/getiri sütunları sınırlı: {exc}")
        from fiyat_para import kur_al
        eur_try, usd_try = kur_al(snap)
        from fiyat_para_fx import FxSpot
        fx = FxSpot(eur_try, usd_try, 0.0, 0.0, "", "snap-only")
        eur_s = usd_s = gbp_s = None

    tefas_sonuc = None
    has_tefas = any(x.tur == "tefas" for x in store.items)
    if profil and tefas_ham and has_tefas and eur_s is not None and usd_s is not None:
        try:
            tefas_sonuc = _tefas_skorlu(
                tefas_ham, profil, rejim,
                gosterim_pb=gpb, eur_s=eur_s, usd_s=usd_s,
            )
        except Exception as exc:
            st.warning(f"TEFAS skorları hesaplanamadı — öneri/skor sütunları sınırlı: {exc}")

    with st.expander("Manuel favori ekle", expanded=len(store.items) == 0):
        with st.form("favori_manuel", border=False):
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                tur = st.selectbox("Tür", list(TUR_ETIKET.keys()), format_func=lambda t: TUR_ETIKET[t])
            with c2:
                sembol = st.text_input("Sembol / kod", placeholder="THYAO veya VUSA.L veya YLR")
            with c3:
                ad = st.text_input("Ad (isteğe bağlı)", placeholder="Türk Hava Yolları")
            if st.form_submit_button("Favorilere ekle", type="primary"):
                if favori_ekle(store, tur, sembol, ad=ad or sembol):
                    st.session_state.favori_store = store
                    st.success(f"{normalize_sembol(tur, sembol)} eklendi.")
                    st.rerun()
                else:
                    st.warning("Sembol boş veya zaten listede.")

    st.subheader("İzleme listesi")
    _favori_izleme_fragment(
        snap,
        tarama=tarama,
        tefas_sonuc=tefas_sonuc,
        tefas_ham=tefas_ham,
        rejim=rejim,
        gpb=gpb,
        fx=fx,
        eur_s=eur_s,
        usd_s=usd_s,
        gbp_s=gbp_s,
    )
