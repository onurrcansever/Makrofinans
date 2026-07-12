# -*- coding: utf-8 -*-
"""Portföy Tahsisi — sade öneri paneli."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from birlesik_oneri import BirlesikOneri
from ui_theme import plotly_base_layout, render_df_table

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


def _hedef_df(oneri: BirlesikOneri) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Varlık sınıfı": h.kategori,
            "Özet": h.arac,
            "Portföy %": f"{h.agirlik_pct:.1f}",
            "Tutar": f"{h.tutar:,.0f} {h.para}",
        }
        for h in oneri.hedef_tablo
    ])


def _arac_dagilim_df(oneri: BirlesikOneri) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Kategori": s.ust_kategori,
            "Araç": s.arac,
            "Açıklama": (s.aciklama or "")[:55],
            "Portföy %": f"{s.portfoy_pct:.2f}",
            "Kategori içi %": f"{s.kategori_ici_pct:.1f}",
            "Tutar": f"{s.tutar:,.0f} {s.para}",
            "Etiket": s.etiket,
        }
        for s in oneri.arac_dagilim
    ])


def birlesik_oneri_paneli(
    oneri: BirlesikOneri,
    para_birimi: str = "EUR",
    vade_etiket: str = "",
) -> None:
    st.subheader("Önerilen portföy dağılımı")
    st.caption(
        f"**Vade ufku:** {vade_etiket or oneri.ozet} · "
        f"Para birimi: **{para_birimi}** · "
        "Üst tablo makro hedef; alt tablo **TEFAS / ETF / BIST** araçlarının kategori içi payları. "
        "BIST önerisi tarama skoruna göredir — Varlıklarım'daki mevcut hisselerden bağımsızdır."
    )

    if oneri.mevcut_notlar:
        for n in oneri.mevcut_notlar:
            st.info(n)

    if oneri.hedef_tablo:
        c_graf, c_tab = st.columns([1, 1.2])

        with c_graf:
            if oneri.grafik_mevcut and (go is not None):
                st.markdown("**Mevcut → hedef (%)**")
                tum = sorted(set(oneri.grafik_hedef) | set(oneri.grafik_mevcut))
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Mevcut",
                    x=tum,
                    y=[oneri.grafik_mevcut.get(k, 0) for k in tum],
                    marker_color="rgba(120,123,134,0.75)",
                ))
                fig.add_trace(go.Bar(
                    name="Hedef",
                    x=tum,
                    y=[oneri.grafik_hedef.get(k, 0) for k in tum],
                    marker_color="rgba(38,166,154,0.85)",
                ))
                fig.update_layout(
                    barmode="group",
                    **plotly_base_layout(title="", height=280, margin=dict(t=20, b=40)),
                )
                st.plotly_chart(fig, use_container_width=True)
            elif oneri.grafik_hedef and go is not None:
                st.markdown("**Hedef dağılım (%)**")
                keys = list(oneri.grafik_hedef.keys())
                fig = go.Figure(go.Bar(
                    x=keys,
                    y=[oneri.grafik_hedef[k] for k in keys],
                    marker_color="rgba(38,166,154,0.85)",
                ))
                fig.update_layout(**plotly_base_layout(title="", height=280, margin=dict(t=20, b=40)))
                st.plotly_chart(fig, use_container_width=True)

        with c_tab:
            st.markdown("**Makro hedef**")
            render_df_table(_hedef_df(oneri), max_height=280)
    else:
        st.warning("Hedef dağılım hesaplanamadı — verileri yenileyin.")

    if oneri.arac_dagilim:
        st.markdown("**Araç içi dağılım**")
        st.caption(
            "Kategori içi %: o sınıfın (ör. BIST %3,3) içinde her araca düşen pay. "
            "Portföy %: toplam portföydeki net ağırlık. TEFAS/BIST: skor; ETF: öncelik sırası."
        )
        render_df_table(_arac_dagilim_df(oneri), max_height=320)

    bugun = [b for b in oneri.bugun if b.etiket == "TUT"]
    if bugun:
        st.markdown("**Bugün — hemen**")
        for b in bugun:
            st.success(
                f"**{b.baslik}:** {b.detay} "
                f"({b.tutar:,.0f} {b.para}) — **{b.etiket}**"
            )
        st.caption(
            "Acil alım/satım yok; mevcut pozisyonunuz makro tabloyla uyumlu. "
            "Vade sonunda yukarıdaki hedef dağılıma geçiş değerlendirilebilir."
        )
    elif oneri.grafik_mevcut:
        st.caption(
            "Bugün için acil aksiyon önerilmiyor. Hedef tablo vade ufku boyunca izlenecek dağılımdır."
        )
