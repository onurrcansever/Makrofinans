# -*- coding: utf-8 -*-
"""Streamlit danışman kartları — koyu terminal teması."""
import streamlit as st

from advice_engine import DanismanRaporu, VarlikTavsiyesi
from ui_theme import (
    ACCENT,
    BORDER,
    DOWN,
    PANEL,
    TEXT,
    TEXT_MUTED,
    UP,
    WARN,
    render_page_header,
)

RENK = {
    "yesil": UP,
    "sari": WARN,
    "kirmizi": DOWN,
    "gri": TEXT_MUTED,
}

SINYAL_BADGE = {
    "GUCLU_AL": ("🟢", UP),
    "AL": ("🔵", ACCENT),
    "TUT": ("🟡", WARN),
    "AZALT": ("🟠", "#d35400"),
    "KACIN": ("🔴", DOWN),
}


def _kart_html(v: VarlikTavsiyesi) -> str:
    badge, bc = SINYAL_BADGE.get(v.sinyal, ("⚪", TEXT_MUTED))
    ok_renk = RENK.get(v.ok_renk, TEXT_MUTED)
    return f"""
    <div style="border:1px solid {BORDER};border-radius:8px;padding:14px;margin-bottom:10px;
                border-left:4px solid {bc};background:{PANEL};">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:1.15em;font-weight:700;color:{TEXT};">{badge} {v.ad}</span>
            <span style="font-size:1.6em;color:{ok_renk};font-weight:600;font-family:Roboto,sans-serif;">{v.ok}</span>
        </div>
        <div style="margin:8px 0;color:{TEXT};">
            <b>{v.sinyal_etiket}</b> · %{v.agirlik_pct:.1f} ({v.tutar_eur:,.0f} EUR) · Güven {v.guven}/100
        </div>
        <div style="font-size:0.95em;margin-bottom:8px;color:{TEXT_MUTED};">{v.baslik}</div>
    </div>
    """


def danisman_paneli(rapor: DanismanRaporu) -> None:
    from ui_theme import render_metric_strip

    render_page_header("AI Danışman", "Kural tabanlı özet · yatırım tavsiyesi değildir")

    if rapor.denetim and rapor.denetim.bulgular:
        st.caption(f"Denetim: {rapor.denetim.ozet}")
        with st.expander("Denetim detayı", expanded=bool(rapor.denetim.kritik_sayisi)):
            for b in rapor.denetim.bulgular:
                st.markdown(
                    f"**{b.baslik}** `{b.kategori}` — {b.oneri}"
                )

    if rapor.oncelik_sirasi:
        render_metric_strip([
            {
                "label": f"{v.ok} {ad}",
                "value": f"%{v.agirlik_pct:.0f}",
                "delta": v.sinyal_etiket,
            }
            for ad in rapor.oncelik_sirasi
            for v in [next(x for x in rapor.varliklar if x.ad == ad)]
        ])

    if rapor.rejim_yorumu:
        _ry = (rapor.rejim_yorumu or "").strip()
        _cum = [c.strip() for c in _ry.replace("\n", " ").split(".") if c.strip()]
        st.caption(". ".join(_cum[:2]) + ("." if _cum[:2] else ""))

    if rapor.genel_ozet:
        with st.expander("Genel değerlendirme", expanded=False):
            st.markdown(rapor.genel_ozet)

    for v in rapor.varliklar:
        st.markdown(_kart_html(v), unsafe_allow_html=True)
        with st.expander(f"{v.ad} — gerekçeler", expanded=False):
            for n in (v.nedenler or []):
                st.markdown(f"- {n}")
            if v.teknik:
                st.caption(f"Teknik: {v.teknik}")
            for d in v.dikkat or []:
                st.markdown(f"- {d}")

    if rapor.kacinilan:
        st.caption(f"Uzak dur: {', '.join(rapor.kacinilan)}")

    if rapor.makro_baglam and rapor.makro_baglam.parcalar:
        with st.expander("Makro bağlam", expanded=False):
            st.caption(f"Güncelleme: {rapor.makro_baglam.guncelleme}")
            for p in rapor.makro_baglam.parcalar:
                st.markdown(
                    f"**{p.ok} {p.baslik}** · {p.canli} — {p.konum}"
                )
