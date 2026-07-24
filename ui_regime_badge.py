# -*- coding: utf-8 -*-
"""Rejim sütunu — görsel rozetler (HIGH_VOL = volatilite, hacim değil)."""
from __future__ import annotations

import html
from typing import Optional

# Koyu panel pastel rozetler
REGIME_SPEC = {
    "TRENDING_UP": {
        "icon": "↗",
        "short": "Trend ↑",
        "color": "#0ECB81",
        "bg": "rgba(14,203,129,0.14)",
        "desc": "Yükselen trend — geri çekilmede alım mantığı aktif",
    },
    "TRENDING_DOWN": {
        "icon": "↘",
        "short": "Trend ↓",
        "color": "#F6465D",
        "bg": "rgba(246,70,93,0.14)",
        "desc": "Düşen trend — yeni alım sinyali üretilmez, sadece izleme",
    },
    "RANGE_BOUND": {
        "icon": "↔",
        "short": "Yatay",
        "color": "#848E9C",
        "bg": "rgba(43,49,57,0.9)",
        "desc": "Yatay bant — bant altı alım / bant üstü kâr alma mantığı",
    },
    "HIGH_VOL": {
        "icon": "⚡",
        "short": "Volatil",
        "color": "#F59E0B",
        "bg": "rgba(245,158,11,0.14)",
        "desc": "Yüksek volatilite — pozisyon boyutu küçültülür, seviyeler genişletilir",
    },
}


def regime_badge_html(
    regime: str,
    detail: str = "",
    *,
    duration_days: Optional[int] = None,
    fresh_change: bool = False,
) -> str:
    spec = REGIME_SPEC.get(regime, {
        "icon": "?",
        "short": regime or "—",
        "color": "#848E9C",
        "bg": "rgba(43,49,57,0.9)",
        "desc": regime or "—",
    })
    tip_parts = [spec["desc"]]
    if detail:
        tip_parts.append(detail)
    if duration_days is not None and duration_days > 0:
        tip_parts.append(f"{duration_days} gündür")
    if fresh_change:
        tip_parts.append("Rejim yeni değişti (son 3 iş günü)")
    tip = html.escape(" · ".join(tip_parts))
    aria = html.escape(f"{spec['short']}: {spec['desc']}")
    dot = (
        '<span style="width:5px;height:5px;border-radius:50%;background:#14B8A6;'
        'display:inline-block;margin-left:3px;" title="Yeni rejim"></span>'
        if fresh_change else ""
    )
    dur = (
        f'<div style="font-size:9px;color:#848E9C;margin-top:1px;">{duration_days} gündür</div>'
        if duration_days and duration_days > 0 else ""
    )
    return (
        f'<span aria-label="{aria}" title="{tip}" style="display:inline-flex;flex-direction:column;'
        f'align-items:flex-start;line-height:1.2;'
        f'font-family:\'IBM Plex Sans\',system-ui,-apple-system,sans-serif;">'
        f'<span style="display:inline-flex;align-items:center;gap:3px;padding:2px 8px;'
        f'border-radius:999px;font-size:11px;font-weight:500;color:{spec["color"]};'
        f'background:{spec["bg"]};white-space:nowrap;">'
        f'<span aria-hidden="true">{spec["icon"]}</span> {html.escape(spec["short"])}{dot}</span>'
        f'{dur}</span>'
    )
