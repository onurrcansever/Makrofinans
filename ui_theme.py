# -*- coding: utf-8 -*-
"""ModulCheck Pro — Enterprise light theme for Streamlit."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union

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
    "AL": (UP, "rgba(22,163,74,0.10)"),
    "DİKKAT": (WARN, "rgba(217,119,6,0.10)"),
    "DIKKAT": (WARN, "rgba(217,119,6,0.10)"),
    "ALMA": (DOWN, "rgba(220,38,38,0.10)"),
    "BEKLE": (TEXT_MUTED, "rgba(100,116,139,0.10)"),
}

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
    "font-size:11px;text-transform:uppercase;letter-spacing:0.45px;font-weight:600;"
    f"text-align:left;padding:10px 12px;border-bottom:1px solid {BORDER};white-space:nowrap;"
)
_TD = (
    f"padding:9px 12px;border-bottom:1px solid #f1f5f9;color:{TEXT};"
    "vertical-align:middle;font-size:13px;"
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


def _format_cell(col: str, val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if col == "Karar":
        key = str(val).strip().upper().replace("DIKKAT", "DİKKAT")
        color, bg = KARAR_STYLES.get(key, (TEXT_MUTED, "rgba(120,123,134,0.12)"))
        return (
            f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f"font-size:11px;font-weight:700;color:{color};background:{bg};"
            f'">{_esc(val)}</span>'
        )
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


def render_df_table(
    df: pd.DataFrame,
    *,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
    max_height: Optional[int] = 480,
) -> None:
    """Stilize HTML tablo."""
    if df.empty:
        st.caption("Tablo boş.")
        return
    pct_cols = pct_cols or {c for c in df.columns if _is_pct_col(c)}
    head = "".join(f'<th style="{_TH}">{_esc(c)}</th>' for c in df.columns)
    rows = []
    for _, row in df.iterrows():
        tds = []
        for col in df.columns:
            val = row[col]
            align = "right" if isinstance(val, (int, float)) or _is_pct_col(col) else "left"
            td_style = f"{_TD}text-align:{align};"
            if isinstance(val, (int, float)) or _is_pct_col(col):
                td_style += _NUM
            if col == badge_col:
                inner = _format_cell(col, val)
            elif col in pct_cols and isinstance(val, (int, float)) and not pd.isna(val):
                sign = "+" if val > 0 else ""
                color = UP if val > 0 else (DOWN if val < 0 else TEXT)
                inner = f'<span style="color:{color};">{sign}{val:.2f}%</span>'
            else:
                inner = _format_cell(col, val)
            tds.append(f'<td style="{td_style}">{inner}</td>')
        rows.append(f"<tr>{''.join(tds)}</tr>")

    wrap = (
        f"overflow-x:auto;margin:8px 0 16px;border:1px solid {BORDER};"
        f"border-radius:8px;background:{PANEL};box-shadow:0 1px 3px rgba(0,0,0,0.05);"
    )
    if max_height:
        wrap += f"max-height:{max_height}px;overflow-y:auto;"
    st.markdown(
        f'<div style="{wrap}">'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f"<thead><tr>{head}</tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>',
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
