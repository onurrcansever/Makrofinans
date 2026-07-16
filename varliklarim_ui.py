# -*- coding: utf-8 -*-
"""Varlıklarım — Streamlit paneli."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from birlesik_oneri import BirlesikOneri
from fiyat_para import (
    fx_serileri_al,
    getiri_sutun_adi,
    kaynak_para_birimi,
    pb_cevir,
    session_gosterim_pb,
    tablo_fx_hazirla,
    tablo_getiri,
)
from portfoy_yoneticisi import yonetici_pozisyon_kolonlari
from macro_data import MacroSnapshot
from ui_theme import plotly_base_layout, render_metric_strip
from favoriler_widgets import render_df_table_interactive
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
    pozisyon_guncelle,
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
    """CRUD sonrası yalnızca varlık değerlemesini düşür — tüm uygulamayı değil."""
    from app_onbellek import varlik_onbellek_dusur
    varlik_onbellek_dusur()


def _portfoy_fingerprint(portfoy: VarlikPortfoy) -> str:
    return "|".join(
        f"{p.id}:{p.tur}:{p.sembol}:{p.miktar:.4f}:{p.maliyet:.4f}:{p.alim_fiyati:.4f}:{p.alim_tarihi}"
        for p in portfoy.pozisyonlar
    )


def _piyasa_pozisyon_var(portfoy) -> bool:
    return any(
        p.tur in ("tefas", "hisse", "etf", "altin", "gumus", "kripto")
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
        # Hisse/ETF/TEFAS: aninda=True boş kalınca alış fiyatı gösterilir
        deger = portfoy_degerle(
            portfoy, snap, cache_salt=str(tick), aninda=not _piyasa_pozisyon_var(portfoy),
        )
        cache[cache_key] = deger
        if len(cache) > 24:
            for k in list(cache.keys())[:-24]:
                del cache[k]
        return deger

    return _hesapla()


@st.dialog("Pozisyon düzenle", width="large")
def _pozisyon_duzenle_dialog(poz_id: str, store: VarlikStore, aktif: VarlikPortfoy) -> None:
    mevcut = next((p for p in aktif.pozisyonlar if p.id == poz_id), None)
    if not mevcut:
        st.warning("Pozisyon bulunamadı.")
        return
    st.markdown(f"**{mevcut.etiket()}** · {mevcut.sembol or '—'}")
    guncellendi = _poz_form_icerigi(
        f"varlik_poz_dlg_{poz_id}",
        "Değişiklikleri kaydet",
        poz=mevcut,
    )
    if guncellendi is not None:
        pozisyon_guncelle(store, aktif.id, guncellendi)
        st.session_state.varlik_store = store
        _onbellek_yenile()
        st.rerun()
    st.markdown("---")
    if st.button("Bu pozisyonu sil", type="primary", key=f"poz_dlg_sil_{poz_id}"):
        pozisyon_sil(store, aktif.id, poz_id)
        st.session_state.varlik_store = store
        _onbellek_yenile()
        st.rerun()


@st.dialog("Yeni pozisyon ekle", width="large")
def _pozisyon_ekle_dialog(store: VarlikStore, aktif: VarlikPortfoy) -> None:
    yeni = _poz_form_icerigi("varlik_poz_ekle_dlg", "Pozisyon ekle")
    if yeni is not None:
        pozisyon_ekle(store, aktif.id, yeni)
        st.session_state.varlik_store = store
        _onbellek_yenile()
        st.rerun()


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
    if tur in ("nakit_eur", "nakit_usd", "nakit_ron"):
        return f"{v:,.4f}"
    if tur in ("tefas", "hisse", "etf"):
        return f"{v:,.4f}"
    return f"{v:,.2f}"


def _vade_etiket(p) -> str:
    from nakit_danisman import vade_bilgisi
    vb = vade_bilgisi(p)
    if vb is None:
        return "—"
    if vb.kalan_gun < 0:
        return f"doldu ({vb.vade_tarihi.strftime('%d.%m')})"
    return f"{vb.kalan_gun} gün ({vb.vade_tarihi.strftime('%d %b')})"


def _pozisyon_tablo(deger, gosterim_pb: str, fx, eur_s, usd_s, gbp_s=None, tarama=None) -> pd.DataFrame:
    from varlik_fiyat import PERIYOTLAR

    periyot_gun = {"1G": 1, "1H": 7, "1A": 30, "3A": 90, "6A": 180}
    getiri_etiket = {et: getiri_sutun_adi(et, gosterim_pb) for et in PERIYOTLAR}
    rows = []
    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        birim_pb = kaynak_para_birimi(
            p.sembol or "", pozisyon_turu=p.tur, varlik_turu=p.tur,
        )
        if p.tur in ("hisse", "etf") and p.sembol:
            birim_pb = kaynak_para_birimi(p.sembol, varlik_turu=p.tur)
        alis = pb_cevir(
            pd_.alim_birim, birim_pb, gosterim_pb, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        ) if pd_.alim_birim > 0 else 0
        guncel = pb_cevir(
            pd_.guncel_birim, birim_pb, gosterim_pb, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        ) if pd_.guncel_birim > 0 else 0
        maliyet = pb_cevir(
            pd_.maliyet_deger, pd_.para, gosterim_pb, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        deger_v = pb_cevir(
            pd_.guncel_deger, pd_.para, gosterim_pb, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        kz = deger_v - maliyet
        kz_pct = (kz / maliyet * 100) if maliyet > 0 else 0
        row = {
            "Araç": p.etiket()[:24],
            "Sembol": (p.sembol or "—")[:10],
            "Miktar": pd_.miktar_goster,
            f"Alış": _fmt_birim(alis, p.tur) if alis > 0 else "—",
            f"Güncel": _fmt_birim(guncel, p.tur) if guncel > 0 else "—",
            f"Maliyet": f"{maliyet:,.0f}",
            f"Değer": f"{deger_v:,.0f}",
            "K/Z": f"{kz:+,.0f} ({kz_pct:+.1f}%)",
            **yonetici_pozisyon_kolonlari(
                p, pd_, tarama=tarama, gosterim_pb=gosterim_pb, fx=fx,
            ),
            "Vade": _vade_etiket(p),
        }
        for et in PERIYOTLAR:
            raw = pd_.getiriler.get(et)
            if p.tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
                row[getiri_etiket[et]] = _fmt_getiri(raw)
            else:
                row[getiri_etiket[et]] = _fmt_getiri(
                    tablo_getiri(
                        raw, gosterim_pb, periyot_gun.get(et, 30), eur_s, usd_s,
                        gbp_seri=gbp_s,
                        sembol=p.sembol or "", varlik_turu=p.tur, asset_pb=birim_pb,
                    )
                )
        rows.append(row)
    return pd.DataFrame(rows)


def _doviz_turler():
    return ("nakit_eur", "nakit_usd", "nakit_ron")


def _varsayilan_pb(tur: str) -> str:
    return {"nakit_eur": "EUR", "nakit_usd": "USD", "nakit_ron": "RON"}.get(tur, "TL")


def _poz_form_icerigi(
    form_key: str,
    submit_etiket: str,
    *,
    tur_baslangic: str = "nakit_tl",
    poz: "VarlikPozisyon | None" = None,
) -> "VarlikPozisyon | None":
    """Ortak pozisyon form içeriği. Yeni ekleme veya düzenleme için kullanılır.
    Düzenlemede poz!=None; form alanları mevcut değerlerle doldurulur.
    Başarılı submit'te VarlikPozisyon döndürür, yoksa None."""
    tur_listesi = list(TUR_SECENEKLERI.keys())
    tur_idx = tur_listesi.index(poz.tur) if poz and poz.tur in tur_listesi else tur_listesi.index(tur_baslangic)

    tur = st.selectbox(
        "Tür",
        tur_listesi,
        index=tur_idx,
        format_func=lambda k: TUR_SECENEKLERI[k],
        key=f"{form_key}_tur",
        disabled=poz is not None,  # düzenlemede tür değiştirilemez
    )
    birimli = tur in ("tefas", "hisse", "etf", "altin", "gumus", "kripto")
    varsayilan_pb = _varsayilan_pb(tur)

    if not poz:
        st.caption(
            "**Nasıl girilir?** "
            + (
                f"{MIKTAR_ETIKET.get(tur, 'Miktar')} ve {ALIM_FIYAT_ETIKET.get(tur, 'alış fiyatı')} — "
                "maliyet otomatik hesaplanır."
                if birimli
                else f"{MIKTAR_ETIKET.get(tur, 'Tutar')} — nakit/mevduat için toplam tutar."
            )
        )

    with st.form(form_key, clear_on_submit=not poz):
        fc1, fc2, fc3 = st.columns(3)
        sembol_disabled = tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat", "altin", "gumus")
        sembol = fc1.text_input(
            "Sembol (THYAO, YIV, CSPX…)",
            value=poz.sembol if poz else "",
            disabled=sembol_disabled,
        )
        ad = fc2.text_input("Açıklama", value=poz.ad if poz else "")

        alim_val = date.today()
        if poz and poz.alim_tarihi:
            try:
                alim_val = date.fromisoformat(poz.alim_tarihi)
            except ValueError:
                pass
        alim = fc3.date_input("Alım tarihi", value=alim_val)

        fc4, fc5, fc6 = st.columns(3)
        miktar_et = MIKTAR_ETIKET.get(tur, "Miktar")
        miktar_default = float(poz.miktar) if poz else 0.0
        miktar = fc4.number_input(
            miktar_et,
            min_value=0.0,
            step=0.01 if birimli else 1.0,
            value=miktar_default,
            format="%.4f" if birimli else "%.2f",
        )
        alim_fiyat_et = ALIM_FIYAT_ETIKET.get(tur, "Alış fiyatı (birim)")
        alim_fiyati_default = float(poz.alim_fiyati) if poz else 0.0
        alim_fiyati = fc5.number_input(
            alim_fiyat_et,
            min_value=0.0,
            step=0.01 if birimli else 0.1,
            value=alim_fiyati_default,
            disabled=not birimli and tur not in _doviz_turler(),
        )
        pb_secenekler = ["TL", "EUR", "USD", "RON"]
        pb_baslangic = (poz.para_birimi if poz and poz.para_birimi in pb_secenekler
                        else varsayilan_pb)
        pb_idx = pb_secenekler.index(pb_baslangic) if pb_baslangic in pb_secenekler else 0
        # key içinde tur dahil: tür değişince widget sıfırlanır, yeni varsayılan geçerli olur
        para = fc6.selectbox(
            "Para birimi", pb_secenekler, index=pb_idx,
            key=f"{form_key}_para_{tur}",
        )

        toplam_maliyet = miktar * alim_fiyati if birimli and alim_fiyati > 0 else miktar
        if birimli and alim_fiyati > 0:
            st.info(f"Tahmini maliyet: **{toplam_maliyet:,.2f} {para}** (= {miktar:,.4f} × {alim_fiyati:,.4f})")
        elif tur in _doviz_turler() and alim_fiyati > 0:
            st.info("Alım kuru kaydedildi — K/Z kur farkından hesaplanır.")
        elif tur in _doviz_turler():
            st.caption("Alım kuru boş bırakılırsa **alım tarihindeki** kur kullanılır.")

        fc7, fc8, fc9 = st.columns(3)
        banka = fc7.text_input("Banka (mevduat)", value=poz.banka if poz else "",
                               disabled=tur != "tl_mevduat")
        faiz = fc8.number_input("Brüt faiz % (mevduat)",
                                min_value=0.0, step=0.5,
                                value=float(poz.brut_faiz) if poz else 0.0,
                                disabled=tur != "tl_mevduat")
        vade_gun = fc9.number_input(
            "Vade (gün, mevduat)",
            min_value=0, max_value=730, step=1,
            value=int(poz.vade_gun) if poz else 0,
            disabled=tur != "tl_mevduat",
            help="Örn. 92 = 3 ay.",
        )

        if st.form_submit_button(submit_etiket, type="primary"):
            if miktar <= 0:
                st.warning("Miktar / tutar girin.")
                return None
            if birimli and alim_fiyati <= 0:
                st.warning(f"{alim_fiyat_et} zorunlu — K/Z için birim alış fiyatı gerekli.")
                return None
            if tur in _doviz_turler():
                maliyet = float(miktar * alim_fiyati) if alim_fiyati > 0 else 0.0
            elif birimli:
                maliyet = miktar * alim_fiyati
            else:
                maliyet = miktar
            return VarlikPozisyon(
                id=poz.id if poz else _uid(),
                tur=tur,
                sembol=sembol.strip().upper(),
                ad=ad.strip(),
                miktar=float(miktar),
                maliyet=float(maliyet),
                alim_fiyati=float(alim_fiyati),
                para_birimi=para,
                alim_tarihi=alim.isoformat(),
                banka=banka,
                vade_gun=int(vade_gun),
                brut_faiz=float(faiz),
            )
    return None


def _pozisyon_formu(store: VarlikStore, aktif: VarlikPortfoy) -> None:
    """Pozisyon ekleme — fiyat yüklenmeden önce gösterilir (vade/mevduat girişi için)."""
    with st.expander("Pozisyon ekle / düzenle", expanded=not aktif.pozisyonlar):
        tab_ekle, tab_duzenle = st.tabs(["➕ Yeni pozisyon", "✏️ Mevcut pozisyonu düzenle"])

        with tab_ekle:
            yeni = _poz_form_icerigi(
                "varlik_poz_form",
                "Pozisyon ekle",
            )
            if yeni is not None:
                pozisyon_ekle(store, aktif.id, yeni)
                st.session_state.varlik_store = store
                _onbellek_yenile()
                st.rerun()

        with tab_duzenle:
            if not aktif.pozisyonlar:
                st.info("Henüz pozisyon yok.")
            else:
                sec_id = st.selectbox(
                    "Düzenlenecek pozisyon",
                    [p.id for p in aktif.pozisyonlar],
                    format_func=lambda i: next(p.etiket() for p in aktif.pozisyonlar if p.id == i),
                    key="varlik_duzenle_sec",
                )
                mevcut_poz = next(p for p in aktif.pozisyonlar if p.id == sec_id)
                guncellendi = _poz_form_icerigi(
                    f"varlik_poz_duzenle_{sec_id}",
                    "Değişiklikleri kaydet",
                    tur_baslangic=mevcut_poz.tur,
                    poz=mevcut_poz,
                )
                if guncellendi is not None:
                    pozisyon_guncelle(store, aktif.id, guncellendi)
                    st.session_state.varlik_store = store
                    _onbellek_yenile()
                    st.rerun()


def oneri_aktar_butonu(
    store: VarlikStore,
    oneri: BirlesikOneri,
    para_birimi: str,
    mevcut_mevduat=None,
) -> None:
    if st.button(
        "Önerilen portföyü yeni portföy olarak kaydet",
        type="primary",
        key="oneri_varlik_aktar",
        use_container_width=True,
    ):
        ad = f"Önerilen portföy ({date.today().strftime('%d.%m.%Y')})"
        yeni = yeni_portfoy(store, ad=ad)
        n = oneri_portfoye_aktar(
            store, yeni.id, oneri,
            para_birimi=para_birimi,
            mevcut_mevduat=mevcut_mevduat,
        )
        store.aktif_id = yeni.id
        kaydet_store(store)
        st.session_state.varlik_store = store
        _onbellek_yenile()
        st.success(
            f"**{yeni.ad}** oluşturuldu — {n} pozisyon eklendi. "
            "**Varlıklarım** bölümünden takip edin."
        )
        st.rerun()


def _render_portfoy_durum_kutusu(aktif, deger, tarama, *, portfoy_kz_pct: float) -> None:
    """Aşama 2C — özet metrikler + isteğe bağlı Claude portföy yorumu."""
    from portfoy_yorum import (
        format_durum_gunu,
        format_portfoy_yorum_markdown,
        portfoy_genel_yorum,
        portfoy_ozet_hesapla,
    )

    ozet = portfoy_ozet_hesapla(
        aktif.pozisyonlar,
        tarama,
        deger_pozisyonlar=getattr(deger, "pozisyonlar", None),
    )
    # Canlı toplam K/Z (gösterim PB) ile hizala
    ozet["portfoy_kz_pct"] = round(float(portfoy_kz_pct or 0), 1)

    gun_tr = format_durum_gunu()
    azalt = ozet.get("azalt_agirlik_pct") or 0
    azalt_uyari = azalt >= 15
    kons = ozet.get("konsantrasyon_uyari")

    st.markdown(
        f"""
<div style="
  border:1px solid rgba(120,120,120,0.35);
  border-radius:10px;
  padding:14px 16px 10px;
  margin:0 0 14px 0;
  background:linear-gradient(180deg, rgba(40,48,56,0.06), rgba(40,48,56,0.02));
">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
    <div style="font-weight:650;font-size:1.05rem;">📊 Portföy Durumu</div>
    <div style="opacity:0.65;font-size:0.85rem;">{gun_tr}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ort. sinyal", f"{ozet.get('ortalama_skor', 0)}/100")
    m2.metric("K/Z", f"{ozet.get('portfoy_kz_pct', 0):+.1f}%")
    m3.metric(
        "AZALT ağırlık",
        f"%{azalt:.1f}",
        delta="dikkat" if azalt_uyari else None,
        delta_color="inverse" if azalt_uyari else "off",
    )
    m4.metric("Pozisyon", f"{ozet.get('toplam_pozisyon', 0)}")
    if kons:
        st.caption(f"⚠ Konsantrasyon: {ozet.get('en_buyuk_sektor', '—')}")
    elif azalt_uyari:
        st.caption(f"⚠ AZALT sinyalli ağırlık: %{azalt:.1f}")

    if st.button(
        "✨ Portföy Yorumu Al",
        key=f"portfoy_yorum_al_{aktif.id}",
        help="Claude ile 2–3 cümlelik portföy özeti (cache 6 saat; sembol gönderilmez)",
    ):
        poz_list = [
            {
                "sembol": p.sembol,
                "miktar": p.miktar,
                "maliyet": p.maliyet,
                "kar_zarar_pct": next(
                    (pd_.kar_zarar_pct for pd_ in deger.pozisyonlar
                     if getattr(pd_, "pozisyon", None) is p
                     or getattr(getattr(pd_, "pozisyon", None), "id", None) == p.id),
                    0.0,
                ),
            }
            for p in aktif.pozisyonlar
        ]
        with st.spinner("Portföy yorumu üretiliyor…"):
            metin, meta = portfoy_genel_yorum(
                ozet, pozisyon_listesi=poz_list,
            )
        st.markdown(format_portfoy_yorum_markdown(metin, meta))
        if meta.get("cache_hit"):
            st.caption("cache hit")
        st.caption(
            "Yasal uyarı: Otomatik özet; yatırım tavsiyesi değildir. "
            "Pozisyon detayları modele gönderilmez."
        )


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
    pb = session_gosterim_pb()
    store.goruntuleme_pb = pb

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
        st.caption(f"Tablo birimi: **{pb}** (sidebar)")
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
        and not getattr(deger_onbellek, "fiyat_bekleniyor", False)
    ):
        deger = deger_onbellek
    else:
        if _piyasa_pozisyon_var(aktif):
            with st.spinner("TEFAS ve piyasa fiyatları güncelleniyor (~10 sn)…"):
                deger = _degerle_portfoy(aktif, snap, veri_tick=veri_tick)
        else:
            deger = _degerle_portfoy(aktif, snap, veri_tick=veri_tick)

    if deger.fiyat_bekleniyor:
        c_yenile, _ = st.columns([1, 3])
        with c_yenile:
            if st.button("↻ Canlı fiyatları getir", key="varlik_fiyat_yenile", use_container_width=True):
                from varlik_fiyat import fiyat_onbellegi_temizle
                fiyat_onbellegi_temizle()
                st.session_state.pop("_varlik_deger_cache", None)
                _onbellek_yenile()
                st.session_state.son_yenileme_sayaci = int(
                    st.session_state.get("son_yenileme_sayaci", 0)
                ) + 1
                st.rerun()
        st.warning(
            "**Toplam şu an maliyet bazında gösteriliyor** — hisse, ETF, fon ve döviz kurları "
            "henüz yüklenmedi. Canlı fiyatlar gelince portföy değeriniz (~1,4M TL civarı) "
            "güncellenecek. **Canlı fiyatları getir** butonuna tıklayın veya 30–60 sn bekleyin."
        )

    if aktif.pozisyonlar:
        kaydet_store(store)

    veri_z = getattr(snap, "veri_zamani", "") or "—"
    st.caption(
        f"Son fiyat güncellemesi: **{veri_z}**"
        + (f" · yükleme **{yukleme_zamani}**" if yukleme_zamani else "")
        + " · **Şimdi yenile** ile tüm veriler yeniden çekilir."
    )

    pb = session_gosterim_pb()
    store.goruntuleme_pb = pb
    ob = st.session_state.get("app_onbellek")
    tarama = getattr(ob, "tarama", None) if ob else None
    fx, eur_s, usd_s, gbp_s, _ = tablo_fx_hazirla(snap, tarama)
    eur_try, usd_try = fx.eur_try, fx.usd_try
    toplam = deger.toplam.get(pb, 0)
    maliyet = deger.maliyet_toplam.get(pb, 0)
    kz = toplam - maliyet
    kz_pct = (kz / maliyet * 100) if maliyet > 0 else 0

    gunluk_snapshot_kaydet(store, aktif.id, deger.toplam)
    st.session_state.varlik_store = store

    # Aşama 2C — Portföy Durumu (daima görünür; yorum butona basınca)
    if aktif.pozisyonlar:
        _render_portfoy_durum_kutusu(
            aktif, deger, tarama, portfoy_kz_pct=kz_pct,
        )

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
        f"**Getiri ({pb}):** kur hareketi dahil · "
        "**1G/1H/1A/3A/6A:** alım tarihinizden itibaren (bugün eklediyseniz 0,00%)"
    )

    if deger.pozisyonlar and go is not None:
        labels = [pd_.pozisyon.etiket()[:20] for pd_ in deger.pozisyonlar]
        vals = [
            deger.pozisyonlar[i].guncel_deger
            for i in range(len(deger.pozisyonlar))
        ]
        pb_vals = [
            _pb_cevir_ui(v, deger.pozisyonlar[i].para, pb, fx)
            for i, v in enumerate(vals)
        ]
        fig = go.Figure(go.Pie(labels=labels, values=pb_vals, hole=0.45))
        fig.update_layout(**plotly_base_layout(title=f"Dağılım ({pb})", height=280))
        st.plotly_chart(fig, use_container_width=True)

    # ── Pozisyonlar + Ekle/Düzenle/Sil ───────────────────────────────────────
    ob = st.session_state.get("app_onbellek")
    tarama = getattr(ob, "tarama", None) if ob else None

    h1c, h2c = st.columns([5, 1])
    with h1c:
        st.subheader("Pozisyonlar")
    with h2c:
        if st.button("➕ Ekle", use_container_width=True, type="primary", key="poz_ekle_btn"):
            _pozisyon_ekle_dialog(store, aktif)

    if deger.pozisyonlar:
        poz_ids = [pd_.pozisyon.id for pd_ in deger.pozisyonlar]

        pending_poz = st.session_state.pop("poz_edit_id", None)
        if pending_poz:
            _pozisyon_duzenle_dialog(pending_poz, store, aktif)

        render_df_table_interactive(
            _pozisyon_tablo(deger, pb, fx, eur_s, usd_s, gbp_s=gbp_s, tarama=tarama),
            key_prefix="poz_tablo",
            max_height=420,
            row_ids=poz_ids,
            action_col=True,
            on_action=lambda pid: st.session_state.update(poz_edit_id=pid),
        )
        st.caption("Satır sonundaki **⋯** ile düzenle veya sil")
    else:
        st.info("Henüz pozisyon yok — **➕ Ekle** butonuna basın veya Portföy Tahsisi'nden öneriyi aktarın.")

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


def _pb_cevir_ui(deger: float, kaynak: str, hedef: str, fx) -> float:
    from varlik_fiyat import _pb_cevir
    return _pb_cevir(
        deger, kaynak, hedef, fx.eur_try, fx.usd_try,
        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
    )
