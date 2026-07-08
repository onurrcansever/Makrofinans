# -*- coding: utf-8 -*-
"""Varlıklarım — Streamlit paneli."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from birlesik_oneri import BirlesikOneri
from macro_data import MacroSnapshot
from ui_theme import plotly_base_layout, render_df_table, render_metric_strip
from varlik_fiyat import PERIYOTLAR, portfoy_degerle
from varliklarim import (
    ALIM_FIYAT_ETIKET,
    MIKTAR_ETIKET,
    TUR_SECENEKLERI,
    VarlikPozisyon,
    VarlikPortfoy,
    VarlikStore,
    gunluk_snapshot_kaydet,
    kaydet_store,
    oneri_portfoye_aktar,
    pozisyon_ekle,
    pozisyon_sil,
    portfoy_sil,
    yeni_portfoy,
    yukle_store,
    _uid,
)

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


def _onbellek_yenile() -> None:
    from app_onbellek import onbellek_gecersiz_kil
    onbellek_gecersiz_kil()


def _portfoy_fingerprint(portfoy: VarlikPortfoy) -> str:
    return "|".join(
        f"{p.id}:{p.tur}:{p.sembol}:{p.miktar:.4f}:{p.maliyet:.4f}:{p.alim_fiyati:.4f}:{p.alim_tarihi}"
        for p in portfoy.pozisyonlar
    )


def _degerle_portfoy(portfoy: VarlikPortfoy, snap: MacroSnapshot, *, veri_tick: int = 0):
    fp = _portfoy_fingerprint(portfoy)
    kur = f"{snap.veri.eur_try}:{snap.veri.usd_try}"
    cache_key = f"vd_{portfoy.id}_{fp}_{kur}_{date.today().isoformat()}_{veri_tick}"
    cache = st.session_state.setdefault("_varlik_deger_cache", {})
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    def _hesapla():
        tick = int(st.session_state.get("son_yenileme_sayaci", 0))
        deger = portfoy_degerle(portfoy, snap, cache_salt=str(tick))
        cache[cache_key] = deger
        if len(cache) > 24:
            for k in list(cache.keys())[:-24]:
                del cache[k]
        return deger

    if portfoy.pozisyonlar:
        with st.spinner("Canlı fiyatlar hesaplanıyor…"):
            return _hesapla()
    return _hesapla()


def _fmt_getiri(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _fmt_birim(v: float, tur: str) -> str:
    if v <= 0:
        return "—"
    if tur in ("altin", "gumus"):
        return f"{v:,.2f}"
    if tur == "kripto":
        return f"{v:,.0f}"
    if tur in ("nakit_eur", "nakit_usd"):
        return f"{v:,.4f}"
    return f"{v:,.2f}"


def _pozisyon_tablo(deger, pb: str) -> pd.DataFrame:
    rows = []
    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        rows.append({
            "Tür": TUR_SECENEKLERI.get(p.tur, p.tur),
            "Araç": p.etiket(),
            "Sembol": p.sembol or "—",
            "Miktar": pd_.miktar_goster,
            "Alış": _fmt_birim(pd_.alim_birim, p.tur),
            "Güncel": _fmt_birim(pd_.guncel_birim, p.tur),
            "Maliyet": f"{pd_.maliyet_deger:,.0f} {pd_.para}",
            "Değer": f"{pd_.guncel_deger:,.0f} {pd_.para}",
            "K/Z": f"{pd_.kar_zarar:+,.0f} ({pd_.kar_zarar_pct:+.1f}%)",
            "1G": _fmt_getiri(pd_.getiriler.get("1G")),
            "1H": _fmt_getiri(pd_.getiriler.get("1H")),
            "1A": _fmt_getiri(pd_.getiriler.get("1A")),
            "3A": _fmt_getiri(pd_.getiriler.get("3A")),
            "6A": _fmt_getiri(pd_.getiriler.get("6A")),
        })
    return pd.DataFrame(rows)


def oneri_aktar_butonu(
    store: VarlikStore,
    oneri: BirlesikOneri,
    para_birimi: str,
    mevcut_mevduat=None,
) -> None:
    aktif = store.aktif()
    if not aktif:
        return
    if st.button(
        f"Önerilen portföyü **{aktif.ad}** portföyüne ekle",
        type="primary",
        key="oneri_varlik_aktar",
        use_container_width=True,
    ):
        n = oneri_portfoye_aktar(
            store, aktif.id, oneri,
            para_birimi=para_birimi,
            mevcut_mevduat=mevcut_mevduat,
        )
        st.session_state.varlik_store = store
        _onbellek_yenile()
        st.success(f"{n} pozisyon eklendi — **Varlıklarım** bölümünden takip edin.")
        st.rerun()


def varliklarim_paneli(
    snap: MacroSnapshot,
    *,
    deger_onbellek=None,
    onbellek_portfoy_id: str = "",
    veri_tick: int = 0,
    yukleme_zamani: str = "",
) -> None:
    st.header("Varlıklarım")
    st.caption(
        "BES platformu gibi portföy takibi — **miktar × birim fiyat** ile canlı K/Z. "
        "Altın/hisse/fon için gram veya adet + alış fiyatı girin. "
        "Veriler `.varliklarim.json` dosyasına kaydedilir."
    )

    if "varlik_store" not in st.session_state:
        st.session_state.varlik_store = yukle_store()
    store: VarlikStore = st.session_state.varlik_store

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        adlar = {p.id: p.ad for p in store.portfoyler}
        sec = st.selectbox(
            "Portföy",
            options=list(adlar.keys()),
            index=max(0, list(adlar.keys()).index(store.aktif_id)) if store.aktif_id in adlar else 0,
            format_func=lambda i: adlar[i],
            key="varlik_portfoy_sec",
        )
        if sec != store.aktif_id:
            store.aktif_id = sec
            kaydet_store(store)
    with c2:
        store.goruntuleme_pb = st.selectbox(
            "Görüntüleme para birimi",
            ["TL", "EUR", "USD"],
            index=["TL", "EUR", "USD"].index(store.goruntuleme_pb),
            key="varlik_pb_sec",
        )
        kaydet_store(store)
    with c3:
        if st.button("+ Yeni portföy", use_container_width=True):
            yeni_portfoy(store)
            st.session_state.varlik_store = store
            _onbellek_yenile()
            st.rerun()

    aktif = store.aktif()
    if not aktif:
        st.warning("Portföy oluşturun.")
        return

    r1, r2, r3 = st.columns(3)
    with r1:
        with st.form(f"portfoy_ad_{aktif.id}", border=False):
            yeni_ad = st.text_input("Portföy adı", value=aktif.ad)
            if st.form_submit_button("Adı kaydet", use_container_width=True):
                ad = yeni_ad.strip()
                if not ad:
                    st.warning("Portföy adı boş olamaz.")
                elif ad != aktif.ad:
                    aktif.ad = ad
                    kaydet_store(store)
                    st.session_state.varlik_store = store
                    st.rerun()
    with r2:
        if st.button("Portföyü sil", use_container_width=True):
            if len(store.portfoyler) > 1:
                portfoy_sil(store, aktif.id)
                st.session_state.varlik_store = store
                _onbellek_yenile()
                st.rerun()
            else:
                st.warning("Son portföy silinemez.")
    with r3:
        st.caption(f"Kaynak: **{aktif.kaynak}** · Oluşturma: {aktif.olusturma or '—'}")
    st.caption("Portföy adını yukarıdaki kutuya yazıp **Adı kaydet**'e basın; üstteki listede görünür.")

    kodlar = [p.sembol for p in aktif.pozisyonlar if p.tur == "tefas" and p.sembol]

    if (
        deger_onbellek is not None
        and onbellek_portfoy_id
        and aktif.id == onbellek_portfoy_id
        and veri_tick == int(st.session_state.get("son_yenileme_sayaci", 0))
    ):
        deger = deger_onbellek
    else:
        deger = _degerle_portfoy(aktif, snap, veri_tick=veri_tick)

    if aktif.pozisyonlar:
        kaydet_store(store)

    veri_z = getattr(snap, "veri_zamani", "") or "—"
    st.caption(
        f"Son fiyat güncellemesi: **{veri_z}**"
        + (f" · yükleme **{yukleme_zamani}**" if yukleme_zamani else "")
        + " · **Şimdi yenile** ile tüm veriler yeniden çekilir."
    )

    pb = store.goruntuleme_pb
    toplam = deger.toplam.get(pb, 0)
    maliyet = deger.maliyet_toplam.get(pb, 0)
    kz = toplam - maliyet
    kz_pct = (kz / maliyet * 100) if maliyet > 0 else 0

    gunluk_snapshot_kaydet(store, aktif.id, deger.toplam)
    st.session_state.varlik_store = store

    render_metric_strip([
        {"label": f"Toplam ({pb})", "value": f"{toplam:,.0f}"},
        {"label": "Maliyet", "value": f"{maliyet:,.0f}"},
        {"label": "K/Z", "value": f"{kz:+,.0f}", "delta": f"{kz_pct:+.2f}%"},
        {"label": "1G", "value": _fmt_getiri(deger.agirlikli_getiri.get("1G"))},
        {"label": "1H", "value": _fmt_getiri(deger.agirlikli_getiri.get("1H"))},
        {"label": "1A", "value": _fmt_getiri(deger.agirlikli_getiri.get("1A"))},
        {"label": "3A", "value": _fmt_getiri(deger.agirlikli_getiri.get("3A"))},
        {"label": "6A", "value": _fmt_getiri(deger.agirlikli_getiri.get("6A"))},
    ])

    # Diğer para birimlerinde aynı portföy
    diger = [x for x in ("TL", "EUR", "USD") if x != pb]
    st.caption(
        " · ".join(f"**{x}:** {deger.toplam.get(x, 0):,.0f}" for x in diger)
        + " — aynı portföy, farklı kur görünümü · "
        "**1G/1H/1A/3A/6A:** alım tarihinizden itibaren (bugün eklediyseniz 0,00%)"
    )

    if deger.pozisyonlar and go is not None:
        labels = [pd_.pozisyon.etiket()[:20] for pd_ in deger.pozisyonlar]
        vals = [
            deger.pozisyonlar[i].guncel_deger
            for i in range(len(deger.pozisyonlar))
        ]
        pb_vals = [
            _pb_cevir_ui(v, deger.pozisyonlar[i].para, pb, snap)
            for i, v in enumerate(vals)
        ]
        fig = go.Figure(go.Pie(labels=labels, values=pb_vals, hole=0.45))
        fig.update_layout(**plotly_base_layout(title=f"Dağılım ({pb})", height=280))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Pozisyonlar")
    if deger.pozisyonlar:
        render_df_table(_pozisyon_tablo(deger, pb), max_height=360)
    else:
        st.info("Henüz pozisyon yok — aşağıdan ekleyin veya Portföy Tahsisi'nden öneriyi aktarın.")

    # Günlük snapshot grafiği
    if store.gunluk_snapshot and go is not None:
        seri = []
        for gun, portfoyler in sorted(store.gunluk_snapshot.items()):
            if aktif.id in portfoyler:
                seri.append({"tarih": gun, "deger": portfoyler[aktif.id].get(pb, 0)})
        if len(seri) >= 2:
            df_s = pd.DataFrame(seri)
            fig2 = go.Figure(go.Scatter(x=df_s["tarih"], y=df_s["deger"], mode="lines+markers"))
            fig2.update_layout(**plotly_base_layout(title=f"Portföy seyri ({pb})", height=260))
            st.plotly_chart(fig2, use_container_width=True)

    with st.expander("Pozisyon ekle / düzenle", expanded=not deger.pozisyonlar):
        tur = st.selectbox(
            "Tür",
            list(TUR_SECENEKLERI.keys()),
            format_func=lambda k: TUR_SECENEKLERI[k],
            key="varlik_tur_sec",
        )
        birimli = tur in ("tefas", "hisse", "etf", "altin", "gumus", "kripto")
        varsayilan_pb = "EUR" if tur == "nakit_eur" else "USD" if tur == "nakit_usd" else "TL"

        st.caption(
            "**Nasıl girilir?** "
            + (
                f"{MIKTAR_ETIKET.get(tur, 'Miktar')} ve {ALIM_FIYAT_ETIKET.get(tur, 'alış fiyatı')} — "
                "maliyet otomatik hesaplanır."
                if birimli
                else f"{MIKTAR_ETIKET.get(tur, 'Tutar')} — nakit/mevduat için toplam tutar."
            )
        )

        with st.form("varlik_poz_form", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            sembol = fc1.text_input(
                "Sembol (THYAO, YIV, CSPX…)",
                "",
                disabled=tur in ("nakit_tl", "nakit_eur", "nakit_usd", "tl_mevduat", "altin", "gumus"),
            )
            ad = fc2.text_input("Açıklama", "")
            alim = fc3.date_input("Alım tarihi", value=date.today())

            fc4, fc5, fc6 = st.columns(3)
            miktar_et = MIKTAR_ETIKET.get(tur, "Miktar")
            miktar = fc4.number_input(miktar_et, min_value=0.0, step=0.01 if birimli else 1000.0, format="%.4f" if birimli else "%.0f")
            alim_fiyat_et = ALIM_FIYAT_ETIKET.get(tur, "Alış fiyatı (birim)")
            alim_fiyati = fc5.number_input(
                alim_fiyat_et,
                min_value=0.0,
                step=0.01 if birimli else 0.5,
                value=0.0,
                disabled=not birimli and tur not in ("nakit_eur", "nakit_usd"),
            )
            para = fc6.selectbox("Para birimi", ["TL", "EUR", "USD"], index=["TL", "EUR", "USD"].index(varsayilan_pb))

            toplam_maliyet = miktar * alim_fiyati if birimli and alim_fiyati > 0 else miktar
            if birimli and alim_fiyati > 0:
                st.info(f"Tahmini maliyet: **{toplam_maliyet:,.2f} {para}** (= {miktar:,.4f} × {alim_fiyati:,.4f})")
            elif tur in ("nakit_eur", "nakit_usd") and alim_fiyati > 0:
                st.info(f"Alım kuru kaydedildi — K/Z kur farkından hesaplanır.")

            fc7, fc8 = st.columns(2)
            banka = fc7.text_input("Banka (mevduat)", "", disabled=tur != "tl_mevduat")
            faiz = fc8.number_input("Brüt faiz % (mevduat)", min_value=0.0, step=0.5, disabled=tur != "tl_mevduat")

            if st.form_submit_button("Pozisyon ekle", type="primary"):
                if miktar <= 0:
                    st.warning("Miktar / tutar girin.")
                elif birimli and alim_fiyati <= 0:
                    st.warning(f"{alim_fiyat_et} zorunlu — K/Z için birim alış fiyatı gerekli.")
                else:
                    maliyet = miktar * alim_fiyati if birimli else miktar
                    poz = VarlikPozisyon(
                        id=_uid(),
                        tur=tur,
                        sembol=sembol.strip().upper(),
                        ad=ad.strip(),
                        miktar=float(miktar),
                        maliyet=float(maliyet),
                        alim_fiyati=float(alim_fiyati),
                        para_birimi=para,
                        alim_tarihi=alim.isoformat(),
                        banka=banka,
                        brut_faiz=float(faiz),
                    )
                    pozisyon_ekle(store, aktif.id, poz)
                    st.session_state.varlik_store = store
                    _onbellek_yenile()
                    st.rerun()

    if aktif.pozisyonlar:
        sil_id = st.selectbox(
            "Silinecek pozisyon",
            [p.id for p in aktif.pozisyonlar],
            format_func=lambda i: next(p.etiket() for p in aktif.pozisyonlar if p.id == i),
            key="varlik_sil_sec",
        )
        if st.button("Seçili pozisyonu sil"):
            pozisyon_sil(store, aktif.id, sil_id)
            st.session_state.varlik_store = store
            _onbellek_yenile()
            st.rerun()


def _pb_cevir_ui(deger: float, kaynak: str, hedef: str, snap) -> float:
    eur_try = snap.veri.eur_try or 35.0
    usd_try = snap.veri.usd_try or eur_try * 1.08
    from varlik_fiyat import _pb_cevir
    return _pb_cevir(deger, kaynak, hedef, eur_try, usd_try)
