# -*- coding: utf-8 -*-
"""TEFAS fon karşılaştırma paneli — Yapı Kredi Portföy odaklı."""
from __future__ import annotations

from typing import List, Optional

import pandas as pd
import streamlit as st

from investor_profile import YatirimProfili
from tefas_data import TefasTaramaSonuc, secili_fon_serisi, yk_fonlari_performans
from tefas_skor import fonlari_skorla, top_oneri
from tefas_universe import KATEGORILER, PARA_BIRIMI, populer_yk_kodlari
from ui_theme import plotly_base_layout, render_df_table, render_metric_strip

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


_ONERI_ETIKET = {
    "GUCLU": "🟢 Güçlü aday",
    "UYGUN": "🟡 Uygun",
    "IZLE": "⚪ İzle",
    "ZAYIF": "🔴 Zayıf",
}


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}%"


def _fmt_fiyat(x: float) -> str:
    return f"{x:,.4f}" if x < 10 else f"{x:,.2f}"


def _tablo_df(sonuc: TefasTaramaSonuc) -> pd.DataFrame:
    rows = []
    for f in sonuc.fonlar:
        rows.append(
            {
                "Öneri": _ONERI_ETIKET.get(f.oneri, f.oneri),
                "Kod": f.kod,
                "Fon": f.kisa_ad,
                "Kategori": f.kategori_etiket,
            "PB": f.para_etiket,
            "Hisse%": f"{f.hisse_pct:.0f}" if f.hisse_pct is not None else "—",
            "Bono%": f"{f.bono_repo_pct:.0f}" if f.bono_repo_pct is not None else "—",
            "Döviz%": f"{f.doviz_pct:.0f}" if f.doviz_pct is not None else "—",
            "Fiyat": _fmt_fiyat(f.fiyat),
                "1H": _pct(f.getiri_1h),
                "1A": _pct(f.getiri_1a),
                "3A": _pct(f.getiri_3a),
                "YBB": _pct(f.getiri_ybb),
                "Skor": f"{f.skor:.0f}",
                "Not": f.skor_notu[:60],
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
    st.header("TEFAS — Yapı Kredi Portföy Fonları")
    st.caption(
        "TEFAS resmi verisi · getiri ve skor profiliniz + makro rejime göre "
        "(yatırım tavsiyesi değildir)."
    )

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

    yenile = st.button("TEFAS verisini yenile", key="tefas_yenile")
    if yenile:
        from tefas_data import _BD_CACHE, _CACHE
        from app_veri import tefas_ham_cek
        from app_onbellek import onbellek_gecersiz_kil

        _CACHE["ts"] = 0.0
        _BD_CACHE["ts"] = 0.0
        _BD_CACHE["df"] = None
        tefas_ham_cek.clear()
        onbellek_gecersiz_kil()

    if ham_onbellek is not None and not ham_onbellek.hata and not yenile:
        ham = ham_onbellek
        st.caption("TEFAS verisi açılışta yüklendi — anında görüntüleniyor.")
    else:
        with st.spinner("TEFAS verisi çekiliyor (Yapı Kredi Portföy fonları)…"):
            ham = yk_fonlari_performans(gun=gun, sadece_yk=True)

    if ham.hata:
        st.error(ham.hata)
        st.info("Kurulum: `pip install pytefas` — TEFAS resmi API kullanılır.")
        return

    mevduat_reel = None
    if mevduat_ozet and getattr(mevduat_ozet, "profil_vade_reel", None) is not None:
        mevduat_reel = mevduat_ozet.profil_vade_reel

    sonuc = fonlari_skorla(ham, profil, rejim=rejim, mevduat_reel=mevduat_reel)

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
    guclu = sum(1 for f in sonuc.fonlar if f.oneri == "GUCLU")
    ort_3a = pd.Series([f.getiri_3a for f in sonuc.fonlar if f.getiri_3a is not None]).median()

    render_metric_strip([
        {"label": "YK fon sayısı", "value": str(len(sonuc.fonlar))},
        {"label": "Güçlü aday", "value": str(guclu)},
        {"label": "Medyan 3A", "value": _pct(float(ort_3a) if pd.notna(ort_3a) else None)},
        {"label": "Kaynak", "value": ham.guncelleme[:16]},
    ])
    st.caption(f"{sonuc.kaynak} · {sonuc.guncelleme}")

    if oneri_list:
        st.subheader("Profilinize göre öne çıkanlar")
        oc1, oc2, oc3 = st.columns(3)
        for i, f in enumerate(oneri_list[:3]):
            col = [oc1, oc2, oc3][i]
            with col:
                st.markdown(
                    f"**{f.kod}** · {_ONERI_ETIKET.get(f.oneri, '')}\n\n"
                    f"{f.kisa_ad}\n\n"
                    f"3A: **{_pct(f.getiri_3a)}** · Skor: **{f.skor:.0f}**\n\n"
                    f"_{f.skor_notu}_"
                )

    st.subheader("Fon karşılaştırma tablosu")
    st.caption(
        f"Makro rejim: **{rejim}** · Profil: *{profil.ozet()}*"
        + (f" · Reel mevduat: **{mevduat_reel:+.1f} pp**" if mevduat_reel is not None else "")
    )
    render_df_table(_tablo_df(sonuc), max_height=520)

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
