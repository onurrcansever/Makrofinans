# -*- coding: utf-8 -*-
"""ModulCheck Pro — koyu finans paneli (terminal hissi; kendi marka)."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union
from urllib.parse import quote

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
except ImportError:  # pragma: no cover
    go = None

# Koyu terminal yüzeyleri (FVT tarzı ilham — kendi palet)
BG = "#181A20"
PANEL = "#1E2329"
PANEL_HOVER = "#2B3139"
BORDER = "#2B3139"
TEXT = "#EAECEF"
TEXT_MUTED = "#848E9C"
UP = "#0ECB81"
UP_BG = "rgba(14,203,129,0.14)"
DOWN = "#F6465D"
DOWN_BG = "rgba(246,70,93,0.14)"
ACCENT = "#14B8A6"
WARN = "#F59E0B"
WARN_BG = "rgba(245,158,11,0.14)"
MUTED_BG = "#2B3139"

_FONT = "'IBM Plex Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
_FONT_TITLE = "'Lexend', 'IBM Plex Sans', system-ui, sans-serif"

KARAR_STYLES = {
    # Signal Engine v2 — Google Finance pastel pills
    "GÜÇLÜ AL": (UP, UP_BG),
    "GUCLU AL": (UP, UP_BG),
    "AL": (UP, UP_BG),
    "İZLE": (TEXT_MUTED, MUTED_BG),
    "IZLE": (TEXT_MUTED, MUTED_BG),
    "BEKLE": (WARN, WARN_BG),
    "AZALT": (DOWN, DOWN_BG),
    # Eski v1 (v2 kapalı)
    "DİKKAT": (WARN, WARN_BG),
    "DIKKAT": (WARN, WARN_BG),
    "ALMA": (DOWN, DOWN_BG),
}

EMIR_STYLES = {
    "AL": (UP, UP_BG),
    "KADEMELI": (WARN, WARN_BG),
    "BEKLE": (TEXT_MUTED, MUTED_BG),
    "TUT": (UP, UP_BG),
    "SAT": (WARN, WARN_BG),
    "KÂR": (WARN, WARN_BG),
    "KAR": (WARN, WARN_BG),
    "ÇIKIŞ": (WARN, WARN_BG),
    "CIKIS": (WARN, WARN_BG),
    "ELDE": (UP, UP_BG),
    "PASIF": (TEXT_MUTED, MUTED_BG),
    "EKLEME": (ACCENT, "rgba(20,184,166,0.14)"),
    "KÜÇÜLT": (DOWN, DOWN_BG),
    "KUCULT": (DOWN, DOWN_BG),
    "AZALT": (DOWN, DOWN_BG),
    "EKLE": (ACCENT, "rgba(20,184,166,0.14)"),
    "UZAK": (DOWN, DOWN_BG),
    "GÜÇLÜ": (UP, UP_BG),
    "GUCLU": (UP, UP_BG),
    "UYGUN": (WARN, WARN_BG),
    "İZLE": (TEXT_MUTED, MUTED_BG),
    "IZLE": (TEXT_MUTED, MUTED_BG),
    "ZAYIF": (DOWN, DOWN_BG),
}

_BADGE_COLS = frozenset({
    "Karar", "Şimdi ne yap?", "Emir", "Plan", "Öneri",
    "Alım/Satış Sinyali", "Pozisyon Önerisi",
})
_MOMENTUM_COLS = frozenset({"Sinyal", "Momentum"})
_TRUNC_COLS = frozenset({"Fon", "Araç", "ETF", "Hisse", "Ad", "Not", "Kategori", "Sembol", "Teknik sinyal"})

# UI sinyal — emoji → zarif glyph (mantık temel_veri'de)
_SINYAL_GLYPH = {
    "🔼": ("▲", UP),
    "🔽": ("▼", DOWN),
    "⏸": ("—", TEXT_MUTED),
    "↑": ("▲", UP),
    "↓": ("▼", DOWN),
    "=": ("—", TEXT_MUTED),
}

_THEME_HTML = Path(__file__).resolve().parent / "static" / "tv_theme.html"
_NUM = (
    f"font-family:{_FONT};"
    "font-variant-numeric:tabular-nums;font-feature-settings:'tnum';"
)
_CELL = (
    f"flex:1 1 130px;min-width:110px;max-width:190px;background:{PANEL};"
    f"border:1px solid {BORDER};border-radius:12px;padding:10px 12px;"
    f"box-shadow:none;"
    f"display:flex;flex-direction:column;gap:3px;min-height:68px;"
)
_STRIP = "display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px;"
_TH = (
    f"position:sticky;top:0;background:{PANEL_HOVER};color:{TEXT_MUTED};"
    f"font-size:11px;text-transform:uppercase;letter-spacing:0.04em;font-weight:600;"
    f"font-family:{_FONT};"
    f"text-align:left;padding:8px 12px;border-bottom:1px solid {BORDER};white-space:nowrap;"
    "vertical-align:middle;line-height:1.2;"
)
_TD = (
    f"padding:8px 12px;height:38px;box-sizing:border-box;"
    f"border-bottom:1px solid {BORDER};color:{TEXT};"
    f"vertical-align:middle;font-size:13px;font-weight:400;line-height:1.25;"
    f"white-space:nowrap;font-family:{_FONT};"
)


def inject_tradingview_theme() -> None:
    """Global tema — st.html ile CSS (metin olarak görünmez)."""
    st.html(_THEME_HTML.read_text(encoding="utf-8"))


def _esc(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return html.escape(str(val))


def render_page_header(title: str, subtitle: str = "") -> None:
    """Sayfa başlığı — koyu panel hiyerarşisi."""
    t = _esc(title)
    sub = _esc(subtitle) if subtitle else ""
    sub_html = f'<p class="mc-page-sub">{sub}</p>' if sub else ""
    st.markdown(
        f'<div class="mc-page-header"><h1 class="mc-page-title">{t}</h1>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def _delta_style(pos: bool) -> str:
    if pos:
        return f"color:{UP};background:{UP_BG};"
    return f"color:{DOWN};background:{DOWN_BG};"


def _pct_pill(val: float, *, with_pct: bool = True) -> str:
    """Google Finance tarzı ▲/▼ yüzde rozeti — sayı formatı aynı."""
    sign = "+" if val > 0 else ""
    suffix = "%" if with_pct else ""
    txt = f"{sign}{val:.2f}{suffix}"
    base = (
        f"display:inline-block;font-family:{_FONT};font-size:13px;font-weight:500;"
        "padding:2px 8px;border-radius:8px;line-height:1.3;white-space:nowrap;"
    )
    if val > 0:
        return f'<span style="{base}color:{UP};background:{UP_BG};">▲ {_esc(txt)}</span>'
    if val < 0:
        return f'<span style="{base}color:{DOWN};background:{DOWN_BG};">▼ {_esc(txt)}</span>'
    return f'<span style="{base}color:{TEXT};background:{MUTED_BG};">{_esc(txt)}</span>'


def format_premarket_pill_html(price_txt: str, pct: Optional[float]) -> str:
    """Premarket — fiyat + % renkli kutu (getiri sütunlarıyla aynı stil)."""
    base = (
        f"display:inline-block;font-family:{_FONT};font-size:13px;font-weight:500;"
        "padding:2px 8px;border-radius:8px;line-height:1.3;white-space:nowrap;"
    )
    px = _esc(price_txt)
    if pct is None:
        return f'<span style="{base}color:{TEXT};background:{MUTED_BG};">{px}</span>'
    sign = "+" if pct > 0 else ""
    tail = _esc(f"{sign}{pct:.1f}%")
    if pct > 0:
        return f'<span style="{base}color:{UP};background:{UP_BG};">▲ {px} ({tail})</span>'
    if pct < 0:
        return f'<span style="{base}color:{DOWN};background:{DOWN_BG};">▼ {px} ({tail})</span>'
    return f'<span style="{base}color:{TEXT};background:{MUTED_BG};">{px} ({tail})</span>'


def _sinyal_cell_html(mark: str, tip: str) -> str:
    glyph, color = _SINYAL_GLYPH.get(mark, (mark or "—", TEXT_MUTED))
    return (
        f'<span style="font-size:12px;font-weight:500;line-height:1;color:{color};'
        f'font-family:{_FONT};" title="{_esc(tip)}">{_esc(glyph)}</span>'
    )


def _fmt_delta(
    delta: Optional[Union[float, str]],
    *,
    fmt: str = "pct",
    inverse: bool = False,
) -> str:
    if delta is None:
        return ""
    base = (
        f"display:inline-block;font-family:{_FONT};"
        "font-size:12px;font-weight:500;padding:2px 8px;border-radius:8px;"
        "line-height:1.3;"
    )
    if isinstance(delta, str):
        txt = delta.strip()
        if not txt or txt == "—":
            return ""
        low = txt.lower()
        pos = not low.startswith("-") and "−" not in txt
        if inverse:
            pos = not pos
        arrow = "▲" if pos else "▼"
        return f'<span style="{base}{_delta_style(pos)}">{arrow} {_esc(txt)}</span>'
    try:
        v = float(delta)
    except (TypeError, ValueError):
        return ""
    pos = v >= 0
    if inverse:
        pos = not pos
    arrow = "▲" if pos else "▼"
    txt = f"{v:+.2f} pp" if fmt == "pp" else f"{v:+.2f}%"
    return f'<span style="{base}{_delta_style(pos)}">{arrow} {_esc(txt)}</span>'


def render_metric_strip(metrics: Sequence[Dict[str, Any]]) -> None:
    """Kompakt metrik kart şeridi — flat koyu panel."""
    cells = []
    for m in metrics:
        label = _esc(m.get("label", ""))
        value = _esc(m.get("value", "—"))
        delta_html = _fmt_delta(
            m.get("delta"),
            fmt=m.get("delta_fmt", "pct"),
            inverse=bool(m.get("delta_inverse")),
        )
        cells.append(
            f'<div style="{_CELL}">'
            f'<div style="font-size:11px;color:{TEXT_MUTED};font-weight:500;'
            f'font-family:{_FONT};letter-spacing:0.03em;text-transform:uppercase;">{label}</div>'
            f'<div style="{_NUM}font-size:18px;font-weight:600;color:{TEXT};line-height:1.2;">{value}</div>'
            f'<div style="min-height:18px;line-height:1.25;">{delta_html}</div>'
            f"</div>"
        )
    st.markdown(f'<div style="{_STRIP}">{"".join(cells)}</div>', unsafe_allow_html=True)


def render_live_banner(text: str, *, live: bool = True) -> None:
    if live:
        st.markdown(
            f'<div class="mc-live-banner">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{UP};'
            f'display:inline-block;flex-shrink:0;"></span>{_esc(text)}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info(text)


def _is_pct_col(name: str) -> bool:
    n = name.lower()
    return "%" in name or "reel" in n or "getiri" in n or "fark" in n or n.endswith(" pp")


def _badge_html(val: Any, styles: dict, *, title: str = "", style_key: str = "") -> str:
    raw = str(val).strip()
    key_src = (style_key or raw).upper()
    key = key_src.split()[0].replace("🟢", "").replace("🟡", "").replace("⚪", "").replace("🔴", "").strip()
    for token in key_src.replace("İ", "I").split():
        if token in styles or token.replace("I", "İ") in styles:
            key = token
            break
    color, bg = styles.get(key, styles.get(key.replace("I", "İ"), (TEXT_MUTED, MUTED_BG)))
    label = raw.split()[-1] if raw.startswith(("🟢", "🟡", "⚪", "🔴")) else raw
    if len(label) > 18:
        label = label[:16] + "…"
    tip_attr = f' title="{_esc(title)}"' if title else ""
    cursor = " cursor:help;" if title else ""
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f"font-size:12px;font-weight:500;font-family:{_FONT};color:{color};background:{bg};"
        f'white-space:nowrap;{cursor}"{tip_attr}>{_esc(label)}</span>'
    )


def score_sparkline_svg(
    values: Sequence[float],
    *,
    width: int = 64,
    height: int = 20,
) -> str:
    """Mini SVG sparkline — tablo hücresi için."""
    if not values or len(values) < 2:
        return "—"
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = i * (width - 4) / max(n - 1, 1) + 2
        y = height - 2 - ((v - lo) / span) * (height - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    color = UP if values[-1] >= values[0] else DOWN
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle;display:block;">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" points="{" ".join(pts)}"/></svg>'
    )


def _format_cell(col: str, val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if isinstance(val, dict) and col == "Pozisyon Önerisi":
        label = str(val.get("label") or "—")
        code = str(val.get("code") or label)
        tip = str(val.get("tip") or "")
        return _badge_html(label, EMIR_STYLES, title=tip, style_key=code)
    if isinstance(val, dict) and col == "Hedef":
        return _esc(val.get("label") or "—")
    if isinstance(val, (list, tuple)) and col in ("90g", "Skor trend"):
        return score_sparkline_svg(val)
    if col in _BADGE_COLS:
        if col in ("Karar", "Şimdi ne yap?", "Alım/Satış Sinyali"):
            raw = str(val).strip()
            key = raw.upper().replace("DIKKAT", "DİKKAT").replace("GUCLU", "GÜÇLÜ")
            # Tam etiket eşleşmesi (GÜÇLÜ AL parçalanmasın)
            if key in KARAR_STYLES:
                style_key = key
            elif raw in KARAR_STYLES:
                style_key = raw
            else:
                style_key = raw
                for cand in ("GÜÇLÜ AL", "GUCLU AL", "AZALT", "İZLE", "IZLE", "BEKLE", "AL", "DİKKAT", "ALMA"):
                    if cand.upper().replace("İ", "I") in key.replace("İ", "I") or cand in raw:
                        style_key = cand if cand in KARAR_STYLES else key
                        break
            color, bg = KARAR_STYLES.get(style_key, KARAR_STYLES.get(raw, (TEXT_MUTED, MUTED_BG)))
            return (
                f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                f"font-size:12px;font-weight:500;font-family:{_FONT};color:{color};background:{bg};"
                f'">{_esc(raw)}</span>'
            )
        return _badge_html(val, EMIR_STYLES)
    if isinstance(val, float):
        if _is_pct_col(col):
            with_pct = "%" in col or "reel" in col.lower()
            return _pct_pill(val, with_pct=with_pct)
        if col in ("Fiyat", "EUR/TRY") or col.startswith("Fiyat ("):
            return f"{val:,.2f}"
        if col in ("Skor", "RSI", "Peer %"):
            return f"{val:.0f}" if col != "RSI" else f"{val:.1f}"
    return _esc(val)


def format_df_cell_html(
    col: str,
    val: Any,
    *,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
) -> str:
    """Tek tablo hücresi HTML içeriği."""
    pct_cols = pct_cols or set()
    if col == "⭐":
        star = "★" if str(val).strip() == "★" else "☆"
        return (
            f'<span style="color:#111827;font-size:17px;font-weight:700;" '
            f'title="Favori">{star}</span>'
        )
    if col in _MOMENTUM_COLS:
        from temel_veri import sinyal_tooltip

        mark = str(val).strip() if val is not None else "⏸"
        tip = sinyal_tooltip(mark, analist_var=True)
        return _sinyal_cell_html(mark, tip)
    if isinstance(val, (list, tuple)) and col in ("90g", "Skor trend"):
        return score_sparkline_svg(val)
    if col in ("Rejim", "Özet", "Premarket") and isinstance(val, str) and "<span" in val:
        return val
    if col in _BADGE_COLS or col == badge_col:
        return _format_cell(col, val)
    if col in pct_cols and isinstance(val, (int, float)) and not pd.isna(val):
        return _pct_pill(float(val), with_pct=True)
    return _format_cell(col, val)


def _df_cell_align(col: str, val: Any, pct_cols: Set[str]) -> str:
    if isinstance(val, (int, float)) or _is_pct_col(col):
        return "right"
    return "left"


def build_df_table_html(
    df: pd.DataFrame,
    *,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
    max_height: Optional[int] = 480,
    truncate_cols: Optional[Set[str]] = None,
    click_table_id: Optional[str] = None,
    action_row_ids: Optional[Sequence[str]] = None,
    nav_page: Optional[str] = None,
) -> str:
    """render_df_table ile aynı HTML — isteğe bağlı tıklanabilir yıldız/işlem."""
    pct_cols = pct_cols or {c for c in df.columns if _is_pct_col(c)}
    trunc = truncate_cols or (_TRUNC_COLS & set(df.columns))
    has_action = (
        click_table_id
        and action_row_ids is not None
        and len(action_row_ids) == len(df)
    )
    data_cols = [c for c in df.columns if c != "İşlem"]
    display_cols = list(data_cols)
    if has_action and "İşlem" not in display_cols:
        display_cols.append("İşlem")
    nav_attr = f' data-qnav="{html.escape(nav_page)}"' if nav_page else ""

    head = "".join(
        f'<th style="{_TH}{"text-align:center;" if c in ("⭐", "İşlem", "Sinyal", "Momentum") else ""}'
        f'{"width:36px;" if c in ("Sinyal", "Momentum") else ""}">{_esc(c)}</th>'
        for c in display_cols
    )
    rows = []
    for ri, (_, row) in enumerate(df.iterrows()):
        tds = []
        for col in display_cols:
            if col == "İşlem" and has_action:
                rid = quote(str(action_row_ids[ri]), safe="")
                act_k = f"act_{click_table_id}"
                tds.append(
                    f'<td style="{_TD}text-align:center;width:40px;">'
                    f'<a href="#" class="row-act-link mc-query-hit" '
                    f'data-qkey="{html.escape(act_k)}" data-qval="{html.escape(rid)}"{nav_attr} '
                    f'title="İşlemler">⋯</a></td>'
                )
                continue
            val = row[col]
            align = _df_cell_align(col, val, pct_cols)
            td_style = f"{_TD}text-align:{align};"
            if isinstance(val, (int, float)) or _is_pct_col(col):
                td_style += _NUM
            if col in trunc:
                td_style += "max-width:140px;overflow:hidden;text-overflow:ellipsis;"
            if col == "⭐" and click_table_id:
                td_style += "text-align:center;width:40px;"
                star = "★" if str(val).strip() == "★" else "☆"
                fav_k = f"fav_{click_table_id}"
                inner = (
                    f'<a href="#" class="fav-star mc-query-hit" '
                    f'data-qkey="{html.escape(fav_k)}" data-qval="{ri}"{nav_attr} '
                    f'style="text-decoration:none;color:#111827;font-size:17px;font-weight:700;" '
                    f'title="Favori ekle/çıkar">{star}</a>'
                )
                tip = "Favori"
            elif col in _MOMENTUM_COLS:
                from temel_veri import sinyal_tooltip

                td_style += "text-align:center;width:36px;"
                skor_h = row["Skor"] if "Skor" in row.index else ""
                analist_var = any(
                    x in str(skor_h) for x in ("💚", "🟡", "🔴", "AL", "TUT", "SAT")
                )
                mark = str(val).strip() if val is not None else "⏸"
                tip = sinyal_tooltip(mark, analist_var=analist_var)
                inner = _sinyal_cell_html(mark, tip)
            else:
                inner = format_df_cell_html(col, val, pct_cols=pct_cols, badge_col=badge_col)
                if isinstance(val, dict) and val.get("tip"):
                    tip = str(val["tip"])
                elif isinstance(val, dict):
                    tip = str(val.get("label") or "")
                elif col == "Özet" and isinstance(val, str) and "<span" in val:
                    tip = "Özet: T teknik · A analist · H haber (AL kararını değiştirmez)"
                else:
                    tip = "" if val is None else str(val)
            td_title = "" if (col == "Pozisyon Önerisi" and isinstance(val, dict)) else _esc(tip)
            tds.append(f'<td style="{td_style}" title="{td_title}">{inner}</td>')
        rows.append(f"<tr>{''.join(tds)}</tr>")

    wrap = (
        f"overflow-x:auto;margin:6px 0 12px;border:1px solid {BORDER};"
        f"border-radius:12px;background:{PANEL};box-shadow:none;"
    )
    if max_height:
        wrap += f"max-height:{max_height}px;overflow-y:auto;"
    return (
        f'<div class="mc-df-table" style="{wrap}">'
        f'<table style="width:100%;border-collapse:collapse;table-layout:auto;'
        f'font-size:13px;font-family:{_FONT};">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_df_table(
    df: pd.DataFrame,
    *,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
    max_height: Optional[int] = 480,
    truncate_cols: Optional[Set[str]] = None,
) -> None:
    """Kompakt HTML tablo — tek satır, taşan metin kesilir."""
    if df.empty:
        st.caption("Tablo boş.")
        return
    st.markdown(
        build_df_table_html(
            df,
            pct_cols=pct_cols,
            badge_col=badge_col,
            max_height=max_height,
            truncate_cols=truncate_cols,
        ),
        unsafe_allow_html=True,
    )


def plotly_base_layout(**extra) -> dict:
    grid_color = BORDER
    layout = dict(
        template="plotly_dark",
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font=dict(family="IBM Plex Sans, system-ui, sans-serif", color=TEXT, size=12),
        margin=dict(l=40, r=20, t=28, b=32),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL_HOVER,
            bordercolor=BORDER,
            font=dict(family="IBM Plex Sans, system-ui, sans-serif", color=TEXT, size=12),
        ),
        xaxis=dict(gridcolor=grid_color, zerolinecolor=grid_color, linecolor=grid_color),
        yaxis=dict(gridcolor=grid_color, zerolinecolor=grid_color, linecolor=grid_color),
        legend=dict(bgcolor="rgba(30,35,41,0.92)", font=dict(color=TEXT_MUTED)),
    )
    layout.update(extra)
    return layout


def plotly_area_line(
    df: pd.DataFrame,
    x_col: str,
    y_cols: Sequence[str],
    *,
    title: str = "",
    height: int = 320,
):
    if go is None:
        st.line_chart(df.set_index(x_col)[list(y_cols)])
        return
    fig = go.Figure()
    colors = [ACCENT, UP, WARN, TEXT_MUTED]
    for i, col in enumerate(y_cols):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[col],
            name=col,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy" if i == 0 else None,
            fillcolor="rgba(20,184,166,0.12)" if i == 0 else None,
        ))
    fig.update_layout(**plotly_base_layout(title=title, height=height))
    st.plotly_chart(fig, use_container_width=True)


def plotly_hbar(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    height: int = 280,
):
    if go is None:
        st.bar_chart(pd.Series(values, index=labels))
        return
    fig = go.Figure(go.Bar(
        x=list(values),
        y=list(labels),
        orientation="h",
        marker=dict(color=ACCENT, opacity=0.85),
    ))
    fig.update_layout(**plotly_base_layout(title=title, height=height))
    fig.update_xaxes(ticksuffix="%")
    st.plotly_chart(fig, use_container_width=True)


def plotly_vbar(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    height: int = 280,
):
    if go is None:
        st.bar_chart(pd.Series(values, index=labels))
        return
    fig = go.Figure(go.Bar(
        x=list(labels),
        y=list(values),
        marker=dict(color=ACCENT, opacity=0.85),
    ))
    fig.update_layout(**plotly_base_layout(title=title, height=height))
    st.plotly_chart(fig, use_container_width=True)
