# -*- coding: utf-8 -*-
"""Streamlit danışman kartları — koyu terminal teması."""
import streamlit as st

from advice_engine import DanismanRaporu, VarlikTavsiyesi
from ui_theme import ACCENT, BORDER, DOWN, PANEL, TEXT, TEXT_MUTED, UP, WARN

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
            <span style="font-size:1.8em;color:{ok_renk};font-weight:bold;font-family:JetBrains Mono,monospace;">{v.ok}</span>
        </div>
        <div style="margin:8px 0;color:{TEXT};">
            <b>{v.sinyal_etiket}</b> · %{v.agirlik_pct:.1f} ({v.tutar_eur:,.0f} EUR) · Güven {v.guven}/100
        </div>
        <div style="font-size:0.95em;margin-bottom:8px;color:{TEXT_MUTED};">{v.baslik}</div>
    </div>
    """


def danisman_paneli(rapor: DanismanRaporu) -> None:
    st.subheader("AI Danışman — neden bu öneri?")
    st.caption("Kural tabanlı dinamik açıklama · canlı veri + denetim · gerçek LLM değil")

    if rapor.denetim and rapor.denetim.bulgular:
        if rapor.denetim.kritik_sayisi:
            st.error(f"⛔ Denetim: {rapor.denetim.ozet}")
        else:
            st.warning(f"⚠️ Denetim: {rapor.denetim.ozet}")

        with st.expander("Denetim raporu — çelişkiler ve veri uyarıları", expanded=rapor.denetim.kritik_sayisi > 0):
            for b in rapor.denetim.bulgular:
                ikon = {"KRITIK": "🔴", "UYARI": "🟡", "BILGI": "🔵"}.get(b.seviye, "⚪")
                st.markdown(
                    f"{ikon} **{b.baslik}** `{b.kategori}`\n\n"
                    f"- **A:** {b.taraf_a}\n"
                    f"- **B:** {b.taraf_b}\n"
                    f"- **Öneri:** {b.oneri}"
                )
    elif rapor.denetim and rapor.denetim.temiz:
        st.success(f"✅ Denetim: {rapor.denetim.ozet}")

    st.markdown(rapor.genel_ozet)
    st.info(rapor.rejim_yorumu)

    if rapor.makro_baglam and rapor.makro_baglam.parcalar:
        st.markdown("#### Canlı makro değerlendirme")
        st.caption(f"Son güncelleme: **{rapor.makro_baglam.guncelleme}**")
        cols = st.columns(2)
        for i, p in enumerate(rapor.makro_baglam.parcalar):
            with cols[i % 2]:
                st.markdown(
                    f"**{p.ok} {p.baslik}** · {p.canli}\n\n"
                    f"{p.konum}\n\n"
                    f"*Trend:* {p.trend}\n\n"
                    f"*Beklenti:* {p.beklenti}\n\n"
                    f"<span style='color:{TEXT_MUTED};font-size:0.85em'>Kaynak: {p.kaynak}</span>",
                    unsafe_allow_html=True,
                )
        st.divider()

    if rapor.oncelik_sirasi:
        cols = st.columns(len(rapor.oncelik_sirasi))
        for i, ad in enumerate(rapor.oncelik_sirasi):
            v = next(x for x in rapor.varliklar if x.ad == ad)
            with cols[i]:
                st.metric(f"{v.ok} {ad}", f"%{v.agirlik_pct:.0f}", v.sinyal_etiket)

    st.divider()

    for v in rapor.varliklar:
        st.markdown(_kart_html(v), unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Neden?**")
            for n in v.nedenler:
                st.markdown(f"- {n}")
            if v.teknik:
                st.caption(f"Teknik: {v.teknik}")
        with col_b:
            if v.dikkat:
                st.markdown("**Dikkat**")
                for d in v.dikkat:
                    st.markdown(f"- ⚠️ {d}")

    if rapor.kacinilan:
        st.warning(f"Şu an uzak durulması önerilen varlıklar: **{', '.join(rapor.kacinilan)}**")

    st.caption(
        "↑ yükseliş trendi · ↓ düşüş · → yatay · Renkler terminal mantığına benzer; "
        "yatırım tavsiyesi değildir."
    )
