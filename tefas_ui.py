# -*- coding: utf-8 -*-
"""TEFAS fon karşılaştırma paneli — Yapı Kredi Portföy odaklı."""
from __future__ import annotations

from typing import List, Optional

import pandas as pd
import streamlit as st

from investor_profile import YatirimProfili
from fiyat_para import (
    fiyat_sutun_adi,
    fx_serileri_al,
    getiri_sutun_adi,
    kur_al,
    session_gosterim_pb,
    tefas_tablo_fiyat,
    tablo_getiri,
    tutar_goster,
)
from tefas_data import TefasTaramaSonuc, secili_fon_serisi, yk_fonlari_performans
from tefas_skor import fonlari_skorla, top_oneri
from tefas_explain import tefas_neden_metni
from tefas_universe import KATEGORILER, PARA_BIRIMI, populer_yk_kodlari, tefas_fiyat_kaynak_pb
from favoriler_widgets import favori_row_keys, favori_yildiz_sutunu, render_df_table_favorili
from ui_theme import plotly_base_layout, render_df_table, render_metric_strip

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


_ONERI_ETIKET = {
    "AL": "🟢 AL",
    "IZLE": "🟡 İZLE",
    "BEKLE": "⚪ BEKLE",
    "ZAYIF": "🔴 Zayıf",
}


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}%"


def _fmt_fiyat(x: float) -> str:
    return f"{x:,.4f}" if x < 10 else f"{x:,.2f}"


_ONERI_KISA = {
    "AL": "AL",
    "IZLE": "İZLE",
    "BEKLE": "BEKLE",
    "ZAYIF": "Zayıf",
}


def _tablo_df(sonuc: TefasTaramaSonuc, snap=None) -> pd.DataFrame:
    gpb = session_gosterim_pb()
    eur_try, usd_try = kur_al(snap) if snap is not None else (35.0, 37.8)
    eur_s, usd_s, gbp_s, eurusd_s, chf_s = fx_serileri_al()
    gbp_usd = float(gbp_s.dropna().iloc[-1]) if gbp_s is not None and not gbp_s.empty else None
    eur_usd = float(eurusd_s.dropna().iloc[-1]) if eurusd_s is not None and not eurusd_s.empty else None
    chf_usd = float(chf_s.dropna().iloc[-1]) if chf_s is not None and not chf_s.empty else None
    fiyat_kol = fiyat_sutun_adi(gpb)
    h1 = getiri_sutun_adi("1H", gpb)
    a1 = getiri_sutun_adi("1A", gpb)
    a3 = getiri_sutun_adi("3A", gpb)
    ybb = getiri_sutun_adi("YBB", gpb)
    bd = pd.DatetimeIndex(usd_s.index) if usd_s is not None and not usd_s.dropna().empty else None
    rows = []
    for f in sonuc.fonlar:
        src_pb = tefas_fiyat_kaynak_pb(f.para_birimi)
        fiyat_g = tefas_tablo_fiyat(
            f.fiyat, gpb, f.para_birimi, eur_try, usd_try,
            gbp_usd=gbp_usd, eur_usd=eur_usd, chf_usd=chf_usd,
        )
        fiyat_disp = _fmt_fiyat(fiyat_g) if fiyat_g is not None else (
            _fmt_fiyat(f.fiyat) if src_pb == gpb else "—"
        )
        asset_pb = src_pb or "TL"
        rows.append(
            {
                **favori_yildiz_sutunu("tefas", f.kod),
                "Öneri": (
                    _ONERI_KISA.get(f.oneri, f.oneri)
                    + ("*" if f.akran_kucuk else "")
                ),
                "Kod": f.kod,
                "Fon": (f.kisa_ad or "")[:30],
                "Kat.": (f.kategori_etiket or "")[:18],
                "PB": f.para_etiket[:8] if f.para_etiket else "—",
                "Hisse%": f"{f.hisse_pct:.0f}" if f.hisse_pct is not None else "—",
                "Bono%": f"{f.bono_repo_pct:.0f}" if f.bono_repo_pct is not None else "—",
                fiyat_kol: fiyat_disp,
                h1: _pct(tablo_getiri(f.getiri_1h, gpb, 7, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                a1: _pct(tablo_getiri(f.getiri_1a, gpb, 30, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                a3: _pct(tablo_getiri(f.getiri_3a, gpb, 90, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                ybb: _pct(tablo_getiri(
                    f.getiri_ybb, gpb, 0, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, ybb=True, bar_dates=bd,
                )),
                "Skor": f"{f.skor:.0f}",
            }
        )
    return pd.DataFrame(rows)


def tefas_paneli(
    snap,
    profil: YatirimProfili,
    rejim: str,
    mevduat_ozet=None,
    ham_onbellek=None,
) -> None:
    from karar_lejant import tefas_lejant_caption, tefas_lejant_detay
    from ui_theme import render_page_header
    from vergi_notu import vergi_notu_caption, vergi_notu_markdown

    render_page_header("TEFAS Fonları", "Yapı Kredi portföy fonları · resmi TEFAS verisi")
    st.caption(tefas_lejant_caption())
    with st.expander("Sözlük / vergi notu", expanded=False):
        st.caption(tefas_lejant_detay())
        st.caption(vergi_notu_caption("tefas"))
        st.markdown(vergi_notu_markdown(kisa=True))

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        gun = st.selectbox(
            "Veri penceresi",
            options=[60, 90, 120],
            index=1,
            format_func=lambda g: f"Son {g} gün",
            help="İlk yükleme ~1–2 dk sürebilir; sonraki açılışlar önbellekten gelir.",
        )
    with col_b:
        kat_filtre = st.selectbox(
            "Kategori",
            ["tumu"] + list(KATEGORILER.keys()),
            format_func=lambda k: "Tümü" if k == "tumu" else KATEGORILER[k],
        )
    with col_c:
        siralama = st.selectbox(
            "Sırala",
            ["Skor (profil)", "3 ay getiri", "1 ay getiri", "YBB getiri", "Kod"],
            index=0,
        )

    yenile = st.button("TEFAS verisini yenile", key="tefas_yenile", type="primary")
    if yenile:
        from tefas_data import _BD_CACHE, _CACHE
        from app_veri import tefas_ham_cek
        from disk_onbellek import disk_sil

        _CACHE["ts"] = 0.0
        _BD_CACHE["ts"] = 0.0
        _BD_CACHE["df"] = None
        disk_sil(f"tefas:{gun}")

    from app_veri import tefas_ham_cek, tefas_yukleniyor

    if yenile:
        with st.spinner("TEFAS verisi çekiliyor (~1–2 dk)…"):
            ham = tefas_ham_cek(gun, zorla=True)
    elif ham_onbellek is not None and not tefas_yukleniyor(ham_onbellek):
        ham = ham_onbellek
        st.caption("TEFAS verisi önbellekten — anında görüntüleniyor.")
    else:
        ham = tefas_ham_cek(gun)

    if tefas_yukleniyor(ham):
        st.info(ham.hata or "TEFAS arka planda yükleniyor — tablolar kısa süre içinde dolacak.")
        return

    if ham.hata:
        st.error(ham.hata)
        st.info("Kurulum: `pip install pytefas` — TEFAS resmi API kullanılır.")
        return

    mevduat_reel = None
    if mevduat_ozet and getattr(mevduat_ozet, "profil_vade_reel", None) is not None:
        mevduat_reel = mevduat_ozet.profil_vade_reel

    gpb = session_gosterim_pb()
    eur_s, usd_s, gbp_s, _, _chf_s = fx_serileri_al()
    sonuc = fonlari_skorla(
        ham, profil, rejim=rejim, mevduat_reel=mevduat_reel,
        gosterim_pb=gpb, eur_seri=eur_s, usd_seri=usd_s, gbp_seri=gbp_s,
        mevduat_ozet=mevduat_ozet,
    )
    try:
        from tefas_skor import assert_tefas_skor_tutarliligi
        assert_tefas_skor_tutarliligi(sonuc.fonlar)
    except AssertionError:
        pass

    if kat_filtre != "tumu":
        sonuc.fonlar = [f for f in sonuc.fonlar if f.kategori == kat_filtre]

    if siralama == "3 ay getiri":
        sonuc.fonlar.sort(key=lambda f: -(f.getiri_3a or -999))
    elif siralama == "1 ay getiri":
        sonuc.fonlar.sort(key=lambda f: -(f.getiri_1a or -999))
    elif siralama == "YBB getiri":
        sonuc.fonlar.sort(key=lambda f: -(f.getiri_ybb or -999))
    elif siralama == "Kod":
        sonuc.fonlar.sort(key=lambda f: f.kod)
    # else already sorted by score

    oneri_list = top_oneri(sonuc, n=5, kategori=kat_filtre if kat_filtre != "tumu" else None)
    al_aday = sum(1 for f in sonuc.fonlar if f.oneri == "AL")
    ort_3a = pd.Series([f.getiri_3a for f in sonuc.fonlar if f.getiri_3a is not None]).median()

    render_metric_strip([
        {"label": "YK fon sayısı", "value": str(len(sonuc.fonlar))},
        {"label": "AL aday", "value": str(al_aday)},
        {"label": "Medyan 3A", "value": _pct(float(ort_3a) if pd.notna(ort_3a) else None)},
        {"label": "Kaynak", "value": ham.guncelleme[:16]},
    ])
    st.caption(
        f"{sonuc.kaynak} · {sonuc.guncelleme} · Skor/getiri bazı: **{gpb}** "
        f"(fon PB → {gpb} kur) · * = küçük akran (<8 fon): AL* / BEKLE* / İZLE*"
    )

    st.subheader("Fon karşılaştırma")
    tefas_meta = [("tefas", f.kod, f.kisa_ad or f.kod) for f in sonuc.fonlar]
    render_df_table_favorili(
        _tablo_df(sonuc, snap=snap),
        tefas_meta,
        key_prefix="tefas_tablo",
        max_height=480,
    )
    st.caption("★/☆ satır içi — favori ekle/çıkar (custom component; fragment; tarama yeniden koşmaz)")

    al_fonlar = [f for f in sonuc.fonlar if f.oneri == "AL"]
    if al_fonlar:
        with st.expander("Neden? — AL önerilerinin gerekçesi", expanded=False):
            for f in al_fonlar:
                st.markdown(tefas_neden_metni(f))
                st.divider()

    st.subheader("Performans grafiği (normalize 100)")
    varsayilan = [f.kod for f in oneri_list[:3]] or populer_yk_kodlari()[:3]
    mevcut_kodlar = {f.kod for f in sonuc.fonlar}
    varsayilan = [k for k in varsayilan if k in mevcut_kodlar]

    secim = st.multiselect(
        "Grafiğe ekle (en fazla 6)",
        options=sorted(mevcut_kodlar),
        default=varsayilan[:3],
        max_selections=6,
        format_func=lambda k: k,
    )

    if secim:
        seri = secili_fon_serisi(secim, gun=gun)
        if not seri.empty:
            pivot = seri.pivot_table(index="tarih", columns="kod", values="endeks", aggfunc="last")
            if go is not None:
                fig = go.Figure()
                for kod in pivot.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=pivot.index,
                            y=pivot[kod],
                            name=str(kod),
                            mode="lines",
                        )
                    )
                fig.update_layout(
                    **plotly_base_layout(
                        title=f"Normalize performans (başlangıç=100) — son {gun} gün",
                        height=360,
                    )
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(pivot)
        else:
            st.warning("Seçili fonlar için seri bulunamadı.")
    else:
        st.info("Grafik için en az bir fon seçin.")

    with st.expander("Kategori rehberi"):
        for kod, etiket in KATEGORILER.items():
            adet = sum(1 for f in sonuc.fonlar if f.kategori == kod)
            st.write(f"**{etiket}** ({adet} fon) — {PARA_BIRIMI.get('TL', '')}")

    st.caption(
        "Detay ve işlem: [TEFAS](https://www.tefas.gov.tr) · "
        "Yapı Kredi fon listesi: [yapikredi.com.tr](https://www.yapikredi.com.tr)"
    )
