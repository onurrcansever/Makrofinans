# -*- coding: utf-8 -*-
"""ModulCheck Pro — Enterprise light theme for Streamlit."""
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

BG = "#eef1f5"
PANEL = "#ffffff"
PANEL_HOVER = "#f8fafc"
BORDER = "#e2e8f0"
TEXT = "#1e293b"
TEXT_MUTED = "#64748b"
UP = "#16a34a"
DOWN = "#dc2626"
ACCENT = "#2563eb"
WARN = "#d97706"

KARAR_STYLES = {
    # Signal Engine v2
    "GÜÇLÜ AL": (UP, "rgba(22,163,74,0.16)"),
    "GUCLU AL": (UP, "rgba(22,163,74,0.16)"),
    "AL": (UP, "rgba(22,163,74,0.10)"),
    "İZLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
    "IZLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
    "BEKLE": (WARN, "rgba(217,119,6,0.10)"),
    "AZALT": (DOWN, "rgba(220,38,38,0.10)"),
    # Eski v1 (v2 kapalı)
    "DİKKAT": (WARN, "rgba(217,119,6,0.10)"),
    "DIKKAT": (WARN, "rgba(217,119,6,0.10)"),
    "ALMA": (DOWN, "rgba(220,38,38,0.10)"),
}

EMIR_STYLES = {
    "AL": (UP, "rgba(22,163,74,0.10)"),
    "KADEMELI": (WARN, "rgba(217,119,6,0.10)"),
    "BEKLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
    "TUT": (UP, "rgba(22,163,74,0.10)"),
    "SAT": (WARN, "rgba(217,119,6,0.10)"),
    "EKLE": (ACCENT, "rgba(37,99,235,0.10)"),
    "UZAK": (DOWN, "rgba(220,38,38,0.10)"),
    "GÜÇLÜ": (UP, "rgba(22,163,74,0.10)"),
    "GUCLU": (UP, "rgba(22,163,74,0.10)"),
    "UYGUN": (WARN, "rgba(217,119,6,0.10)"),
    "İZLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
    "IZLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
    "ZAYIF": (DOWN, "rgba(220,38,38,0.10)"),
}

_BADGE_COLS = frozenset({"Karar", "Emir", "Plan", "Öneri"})
_TRUNC_COLS = frozenset({"Fon", "Araç", "ETF", "Hisse", "Ad", "Not", "Kategori", "Sembol", "Teknik sinyal"})

_THEME_HTML = Path(__file__).resolve().parent / "static" / "tv_theme.html"
_NUM = (
    "font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "font-variant-numeric:tabular-nums;font-feature-settings:'tnum';"
)
_CELL = (
    f"flex:1 1 145px;min-width:135px;max-width:220px;background:{PANEL};"
    f"border:1px solid {BORDER};border-radius:10px;padding:14px 16px;"
    f"box-shadow:0 1px 2px rgba(15,23,42,0.06);"
    f"display:flex;flex-direction:column;gap:6px;min-height:88px;"
)
_STRIP = "display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 18px;"
_TH = (
    f"position:sticky;top:0;background:#f1f5f9;color:{TEXT_MUTED};"
    "font-size:10px;text-transform:uppercase;letter-spacing:0.4px;font-weight:600;"
    f"text-align:left;padding:6px 8px;border-bottom:1px solid {BORDER};white-space:nowrap;"
    "vertical-align:middle;line-height:1.2;"
)
_TD = (
    f"padding:5px 8px;border-bottom:1px solid #f1f5f9;color:{TEXT};"
    "vertical-align:middle;font-size:12px;line-height:1.25;white-space:nowrap;"
)


def inject_tradingview_theme() -> None:
    """Global tema — st.html ile CSS (metin olarak görünmez)."""
    st.html(_THEME_HTML.read_text(encoding="utf-8"))


def _esc(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return html.escape(str(val))


def _delta_style(pos: bool) -> str:
    if pos:
        return f"color:{UP};background:rgba(22,163,74,0.09);"
    return f"color:{DOWN};background:rgba(220,38,38,0.09);"


def _fmt_delta(
    delta: Optional[Union[float, str]],
    *,
    fmt: str = "pct",
    inverse: bool = False,
) -> str:
    if delta is None:
        return ""
    base = (
        "display:inline-block;font-family:Inter,sans-serif;"
        "font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;"
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
    """Watchlist tarzı yatay metrik şeridi — inline style (CSS bağımsız)."""
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
            f'<div style="font-size:10px;color:{TEXT_MUTED};text-transform:uppercase;'
            f'letter-spacing:0.5px;font-weight:600;font-family:Inter,sans-serif;">{label}</div>'
            f'<div style="{_NUM}font-size:20px;font-weight:700;color:{TEXT};line-height:1.25;">{value}</div>'
            f'<div style="min-height:20px;line-height:1.3;">{delta_html}</div>'
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


def _badge_html(val: Any, styles: dict) -> str:
    raw = str(val).strip()
    key = raw.upper().split()[0].replace("🟢", "").replace("🟡", "").replace("⚪", "").replace("🔴", "").strip()
    for token in raw.upper().replace("İ", "I").split():
        if token in styles or token.replace("I", "İ") in styles:
            key = token
            break
    color, bg = styles.get(key, styles.get(key.replace("I", "İ"), (TEXT_MUTED, "rgba(120,123,134,0.12)")))
    label = raw.split()[-1] if raw.startswith(("🟢", "🟡", "⚪", "🔴")) else raw
    if len(label) > 14:
        label = label[:12] + "…"
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f"font-size:10px;font-weight:700;color:{color};background:{bg};"
        f'white-space:nowrap;">{_esc(label)}</span>'
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
    if isinstance(val, (list, tuple)) and col in ("90g", "Skor trend"):
        return score_sparkline_svg(val)
    if col in _BADGE_COLS:
        if col == "Karar":
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
            color, bg = KARAR_STYLES.get(style_key, KARAR_STYLES.get(raw, (TEXT_MUTED, "rgba(120,123,134,0.12)")))
            return (
                f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
                f"font-size:10px;font-weight:700;color:{color};background:{bg};"
                f'">{_esc(raw)}</span>'
            )
        return _badge_html(val, EMIR_STYLES)
    if isinstance(val, float):
        if _is_pct_col(col):
            sign = "+" if val > 0 else ""
            color = UP if val > 0 else (DOWN if val < 0 else TEXT)
            suffix = "%" if "%" in col or "reel" in col.lower() else ""
            return f'<span style="color:{color};">{sign}{val:.2f}{suffix}</span>'
        if col in ("Fiyat", "EUR/TRY"):
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
    if col == "Sinyal":
        from temel_veri import sinyal_tooltip

        mark = str(val).strip() if val is not None else "⏸"
        tip = sinyal_tooltip(mark, analist_var=True)
        return (
            f'<span style="font-size:15px;line-height:1;" title="{_esc(tip)}">'
            f"{_esc(mark)}</span>"
        )
    if isinstance(val, (list, tuple)) and col in ("90g", "Skor trend"):
        return score_sparkline_svg(val)
    if col == "Rejim" and isinstance(val, str) and "<span" in val:
        return val
    if col in _BADGE_COLS or col == badge_col:
        return _format_cell(col, val)
    if col in pct_cols and isinstance(val, (int, float)) and not pd.isna(val):
        sign = "+" if val > 0 else ""
        color = UP if val > 0 else (DOWN if val < 0 else TEXT)
        return f'<span style="color:{color};">{sign}{val:.2f}%</span>'
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
        f'<th style="{_TH}{"text-align:center;" if c in ("⭐", "İşlem", "Sinyal") else ""}'
        f'{"width:36px;" if c == "Sinyal" else ""}">{_esc(c)}</th>'
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
            elif col == "Sinyal":
                from temel_veri import sinyal_tooltip

                td_style += "text-align:center;width:36px;"
                skor_h = row["Skor"] if "Skor" in row.index else ""
                analist_var = any(
                    x in str(skor_h) for x in ("💚", "🟡", "🔴", "AL", "TUT", "SAT")
                )
                mark = str(val).strip() if val is not None else "⏸"
                tip = sinyal_tooltip(mark, analist_var=analist_var)
                inner = (
                    f'<span style="font-size:15px;line-height:1;" title="{_esc(tip)}">'
                    f"{_esc(mark)}</span>"
                )
            else:
                inner = format_df_cell_html(col, val, pct_cols=pct_cols, badge_col=badge_col)
                tip = "" if val is None else str(val)
            tds.append(f'<td style="{td_style}" title="{_esc(tip)}">{inner}</td>')
        rows.append(f"<tr>{''.join(tds)}</tr>")

    wrap = (
        f"overflow-x:auto;margin:6px 0 12px;border:1px solid {BORDER};"
        f"border-radius:8px;background:{PANEL};box-shadow:0 1px 2px rgba(0,0,0,0.04);"
    )
    if max_height:
        wrap += f"max-height:{max_height}px;overflow-y:auto;"
    return (
        f'<div class="mc-df-table" style="{wrap}">'
        f'<table style="width:100%;border-collapse:collapse;table-layout:auto;font-size:12px;">'
        f"<thead><tr>{head}</tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>'
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
    grid_color = "#e2e8f0"
    layout = dict(
        template="plotly_white",
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font=dict(family="Inter, sans-serif", color=TEXT, size=12),
        margin=dict(l=48, r=24, t=36, b=40),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL,
            bordercolor=BORDER,
            font=dict(family="JetBrains Mono, monospace", color=TEXT, size=12),
        ),
        xaxis=dict(gridcolor=grid_color, zerolinecolor=grid_color, linecolor=grid_color),
        yaxis=dict(gridcolor=grid_color, zerolinecolor=grid_color, linecolor=grid_color),
        legend=dict(bgcolor="rgba(255,255,255,0.8)", font=dict(color=TEXT_MUTED)),
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
            fillcolor="rgba(37,99,235,0.07)" if i == 0 else None,
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
