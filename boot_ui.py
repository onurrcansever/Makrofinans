# -*- coding: utf-8 -*-
"""Açılış — film tarzı aşama ekranı (Streamlit)."""
from __future__ import annotations

import html
from typing import List, Sequence

import streamlit as st

from ui_theme import ACCENT, BORDER, PANEL, TEXT, TEXT_MUTED, UP, _FONT


# (id, başlık, alt açıklama)
BOOT_STAGES = [
    ("fx", "Kur omurgası", "EUR / USD / GBP / CHF ve makro çaprazlar"),
    ("quotes", "Canlı fiyat önbelleği", "Evren kotasyonları Yahoo’dan tazeleniyor"),
    ("scan", "Hisse & ETF taraması", "Barlar, teknik göstergeler, Signal Engine"),
    ("analist", "Analist değerlendirmeleri", "Konsensüs, hedef fiyat, F/K alanları"),
    ("ready", "Sistem kilidi", "Güvenilir oturum verisi hazır"),
]


def _esc(s: object) -> str:
    return html.escape(str(s or ""))


def render_boot_frame(
    *,
    active_id: str,
    done_ids: Sequence[str],
    detail: str = "",
    pct: float = 0.0,
    brand: str = "TL Yatırım Asistanı",
    counter: str = "",
    counter_label: str = "",
) -> None:
    """Ortada tek kart — aşamalar + yakıt sayacı + anlık satır."""
    done = set(done_ids or [])
    pct = max(0.0, min(100.0, float(pct)))
    rows: List[str] = []
    for sid, title, sub in BOOT_STAGES:
        if sid in done or (active_id == "ready" and sid == "ready"):
            mark = f'<span style="color:{UP};font-weight:600;">✓</span>'
            state = "done"
            opacity = "1"
        elif sid == active_id:
            mark = f'<span style="color:{ACCENT};font-weight:700;">▸</span>'
            state = "active"
            opacity = "1"
        else:
            mark = f'<span style="color:{TEXT_MUTED};">○</span>'
            state = "todo"
            opacity = "0.55"
        pulse = (
            "animation:bootPulse 1.4s ease-in-out infinite;"
            if state == "active"
            else ""
        )
        rows.append(
            f'<div style="display:flex;gap:14px;align-items:flex-start;'
            f'padding:10px 0;opacity:{opacity};{pulse}">'
            f'<div style="width:22px;text-align:center;padding-top:2px;">{mark}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:15px;font-weight:{"600" if state=="active" else "500"};'
            f'color:{TEXT};font-family:{_FONT};">{_esc(title)}</div>'
            f'<div style="font-size:12px;color:{TEXT_MUTED};margin-top:2px;'
            f'font-family:{_FONT};">{_esc(sub)}</div>'
            f"</div></div>"
        )

    bar_w = f"{pct:.1f}%"
    st.html(
        f"""
<style>
@keyframes bootPulse {{
  0%,100% {{ opacity: 1; }}
  50% {{ opacity: 0.72; }}
}}
@keyframes bootDot {{
  0%,100% {{ transform: scale(1); opacity: 1; }}
  50% {{ transform: scale(1.35); opacity: 0.55; }}
}}
@keyframes bootFade {{
  0%,100% {{ opacity: 1; }}
  50% {{ opacity: 0.65; }}
}}
</style>
<div style="max-width:560px;margin:8vh auto 0;padding:28px 32px 24px;
  background:{PANEL};border:1px solid {BORDER};border-radius:16px;
  box-shadow:0 12px 40px rgba(32,33,36,0.08);font-family:{_FONT};">
  <div style="font-size:11px;letter-spacing:0.08em;text-transform:uppercase;
    color:{TEXT_MUTED};font-weight:600;">Sistem açılışı</div>
  <div style="font-size:26px;font-weight:600;color:{TEXT};margin:6px 0 4px;">
    {_esc(brand)}</div>
  <div style="font-size:14px;color:{TEXT_MUTED};margin-bottom:18px;">
    Veriler aşama aşama doğrulanıyor — hazır olana kadar izleyin.
  </div>
  {"".join(rows)}
  {f'''
  <div style="margin:16px 0 4px;padding:14px 16px;background:#f8f9fa;
    border-radius:12px;border:1px solid {BORDER};text-align:center;">
    <div style="font-size:11px;color:{TEXT_MUTED};letter-spacing:0.06em;
      text-transform:uppercase;">{_esc(counter_label or "Sayaç")}</div>
    <div style="font-size:36px;font-weight:600;color:{ACCENT};font-variant-numeric:tabular-nums;
      letter-spacing:0.02em;line-height:1.2;margin-top:4px;animation:bootFade 1.2s ease-in-out infinite;">
      {_esc(counter)}</div>
  </div>
  ''' if counter else ''}
  <div style="margin-top:18px;height:6px;background:#e8eaed;border-radius:99px;overflow:hidden;">
    <div style="height:100%;width:{bar_w};background:{ACCENT};border-radius:99px;
      transition:width 0.25s ease;"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:8px;
    font-size:12px;color:{TEXT_MUTED};">
    <span>İlerleme</span><span>{pct:.0f}%</span>
  </div>
  <div style="margin-top:14px;font-size:13px;color:{TEXT};font-family:{_FONT};
    min-height:1.5em;display:flex;align-items:center;gap:8px;">
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;
      background:{ACCENT};animation:bootDot 0.8s ease-in-out infinite;"></span>
    <span style="color:{TEXT_MUTED};animation:bootFade 1.2s ease-in-out infinite;">
      {_esc(detail) if detail else "Çalışıyor…"}
    </span>
  </div>
</div>
"""
    )


def boot_placeholders():
    """Yenilenebilir slotlar — aşama güncellemesi için."""
    return st.empty()


def update_boot(
    frame,
    *,
    active_id: str,
    done_ids: Sequence[str],
    detail: str = "",
    pct: float = 0.0,
    counter: str = "",
    counter_label: str = "",
) -> None:
    with frame.container():
        render_boot_frame(
            active_id=active_id,
            done_ids=done_ids,
            detail=detail,
            pct=pct,
            counter=counter,
            counter_label=counter_label,
        )
