# -*- coding: utf-8 -*-
"""Portföy Tahsisi — sade öneri paneli."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from birlesik_oneri import BirlesikOneri
from fiyat_para import session_gosterim_pb, tablo_fx_hazirla, tutar_goster
from ui_theme import plotly_base_layout, render_df_table
from vergi_notu import vergi_notu_caption

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


def _fx_ctx(snap, tarama=None) -> tuple[float, float, dict[str, float]]:
    """Yahoo FX spot — EUR/GBP/CHF→USD dönüşümü için gbp_usd + eur_usd + chf_usd."""
    fx, _, _, _, _ = tablo_fx_hazirla(snap, tarama)
    return fx.eur_try, fx.usd_try, {
        "gbp_usd": fx.gbp_usd,
        "eur_usd": fx.eur_usd,
        "chf_usd": getattr(fx, "chf_usd", None),
    }


def _tutar(
    tutar: float,
    para: str,
    gpb: str,
    eur_try: float,
    usd_try: float,
    fx_kw: dict[str, float],
) -> str:
    return tutar_goster(tutar, para, gpb, eur_try, usd_try, **fx_kw)


def _hedef_df(
    oneri: BirlesikOneri,
    gpb: str,
    eur_try: float,
    usd_try: float,
    fx_kw: dict[str, float],
) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Varlık sınıfı": h.kategori,
            "Özet": h.arac,
            "Portföy %": f"{h.agirlik_pct:.1f}",
            "Tutar": _tutar(h.tutar, h.para, gpb, eur_try, usd_try, fx_kw),
        }
        for h in oneri.hedef_tablo
    ])


def _arac_dagilim_df(
    oneri: BirlesikOneri,
    gpb: str,
    eur_try: float,
    usd_try: float,
    fx_kw: dict[str, float],
) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Kategori": s.ust_kategori,
            "Araç": s.arac,
            "Açıklama": (s.aciklama or "")[:55],
            "Portföy %": f"{s.portfoy_pct:.2f}",
            "Kategori içi %": f"{s.kategori_ici_pct:.1f}",
            "Tutar": _tutar(s.tutar, s.para, gpb, eur_try, usd_try, fx_kw),
            "Etiket": s.etiket,
        }
        for s in oneri.arac_dagilim
    ])


def birlesik_oneri_paneli(
    oneri: BirlesikOneri,
    para_birimi: str = "EUR",
    vade_etiket: str = "",
    snap=None,
    tarama: Any = None,
) -> None:
    gpb = session_gosterim_pb()
    try:
        eur_try, usd_try, fx_kw = _fx_ctx(snap, tarama)
    except Exception as exc:
        from fiyat_para_fx import FxUnavailableError
        if isinstance(exc, FxUnavailableError):
            st.error(f"FX kurları yüklenemedi — tutarlar gösterilemiyor: {exc}")
            return
        raise

    st.subheader("Önerilen dağılım")
    st.caption(
        f"{vade_etiket or oneri.ozet} · {para_birimi} · görünüm {gpb}"
    )

    if oneri.mevcut_notlar:
        with st.expander(f"Notlar ({len(oneri.mevcut_notlar)})", expanded=False):
            for n in oneri.mevcut_notlar:
                st.caption(n)

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
            render_df_table(_hedef_df(oneri, gpb, eur_try, usd_try, fx_kw), max_height=280)
    else:
        st.warning("Hedef dağılım hesaplanamadı — verileri yenileyin.")

    if getattr(oneri, "dilim_kararlari", None):
        st.markdown("**Dinamik araç seçimi**")
        st.caption(
            "Makro dilim içinde mevduat / TEFAS / fiziki / ETF karşılaştırması "
            "(net proxy = beklenen brüt − TGO/TER/makas/stopaj sürüklemesi). "
            + vergi_notu_caption("tefas")
        )
        dk_rows = []
        for k in oneri.dilim_kararlari:
            yedek = f"{k.yedek.ad} (~%{k.yedek.net_proxy:.1f})" if k.yedek else "—"
            maliyet = (
                " · ".join(f"{a} %{v:.2f}" for a, v in (k.kazanan.maliyet_kalemleri or {}).items() if v)
                or "—"
            )
            dk_rows.append({
                "Dilim": k.dilim,
                "Kazanan": k.kazanan.ad,
                "Tür": k.kazanan.tur,
                "Net proxy %": f"{k.kazanan.net_proxy:.1f}",
                "Maliyet": maliyet[:48],
                "Yedek": yedek,
                "Neden": (k.gerekce or "")[:90],
            })
        if dk_rows:
            render_df_table(pd.DataFrame(dk_rows), max_height=260)

    if oneri.arac_dagilim:
        st.markdown("**Araç içi dağılım**")
        st.caption(
            "Kategori içi %: o sınıfın (ör. BIST %3,3) içinde her araca düşen pay. "
            "Portföy %: toplam portföydeki net ağırlık (TEFAS→TL, ETF→FX içinden). "
            "TEFAS/BIST: skor; ETF: öncelik sırası."
        )
        render_df_table(_arac_dagilim_df(oneri, gpb, eur_try, usd_try, fx_kw), max_height=320)

    bugun = [b for b in oneri.bugun if b.etiket == "TUT"]
    if bugun:
        st.markdown("**Bugün — hemen**")
        for b in bugun:
            st.success(
                f"**{b.baslik}:** {b.detay} "
                f"({_tutar(b.tutar, b.para, gpb, eur_try, usd_try, fx_kw)}) — **{b.etiket}**"
            )
        st.caption(
            "Acil alım/satım yok; mevcut pozisyonunuz makro tabloyla uyumlu. "
            "Vade sonunda yukarıdaki hedef dağılıma geçiş değerlendirilebilir."
        )
    elif oneri.grafik_mevcut:
        st.caption(
            "Bugün için acil aksiyon önerilmiyor. Hedef tablo vade ufku boyunca izlenecek dağılımdır."
        )
