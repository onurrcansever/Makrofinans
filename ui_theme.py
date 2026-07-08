# -*- coding: utf-8 -*-
"""TradingView-inspired dark terminal theme for Streamlit."""
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

BG = "#131722"
PANEL = "#1e222d"
PANEL_HOVER = "#2a2e39"
BORDER = "#2a2e39"
TEXT = "#d1d4dc"
TEXT_MUTED = "#787b86"
UP = "#26a69a"
DOWN = "#ef5350"
ACCENT = "#2962ff"
WARN = "#ff9800"

KARAR_STYLES = {
    "AL": (UP, "rgba(38,166,154,0.10)"),
    "DİKKAT": (WARN, "rgba(255,152,0,0.10)"),
    "DIKKAT": (WARN, "rgba(255,152,0,0.10)"),
    "ALMA": (DOWN, "rgba(239,83,80,0.10)"),
    "BEKLE": (TEXT_MUTED, "rgba(120,123,134,0.12)"),
}

_THEME_HTML = Path(__file__).resolve().parent / "static" / "tv_theme.html"
_MONO = "font-family:'JetBrains Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;"
_CELL = (
    f"flex:1 1 120px;min-width:110px;max-width:180px;background:{PANEL};"
    f"border:1px solid {BORDER};border-radius:8px;padding:12px 14px;"
)
_STRIP = "display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 16px;"
_TH = (
    f"position:sticky;top:0;background:{PANEL};color:{TEXT_MUTED};"
    "font-size:11px;text-transform:uppercase;letter-spacing:0.45px;"
    f"text-align:left;padding:10px 12px;border-bottom:1px solid {BORDER};white-space:nowrap;"
)
_TD = f"padding:9px 12px;border-bottom:1px solid {BORDER};color:{TEXT};vertical-align:middle;"


def inject_tradingview_theme() -> None:
    """Global tema — st.html ile CSS (metin olarak görünmez)."""
    st.html(_THEME_HTML.read_text(encoding="utf-8"))


def _esc(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return html.escape(str(val))


def _delta_style(pos: bool) -> str:
    if pos:
        return f"color:{UP};background:rgba(38,166,154,0.08);"
    return f"color:{DOWN};background:rgba(239,83,80,0.08);"


def _fmt_delta(
    delta: Optional[Union[float, str]],
    *,
    fmt: str = "pct",
    inverse: bool = False,
) -> str:
    if delta is None:
        return ""
    base = (
        "display:inline-block;margin-top:6px;font-family:'JetBrains Mono',ui-monospace,monospace;"
        "font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;"
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
            f'<div style="font-size:11px;color:{TEXT_MUTED};text-transform:uppercase;'
            f'letter-spacing:0.45px;margin-bottom:6px;">{label}</div>'
            f'<div style="{_MONO}font-size:21px;font-weight:600;color:{TEXT};">{value}</div>'
            f"{delta_html}</div>"
        )
    st.markdown(f'<div style="{_STRIP}">{"".join(cells)}</div>', unsafe_allow_html=True)


def render_live_banner(text: str, *, live: bool = True) -> None:
    if live:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;padding:8px 14px;margin:8px 0 12px;'
            f"background:rgba(38,166,154,0.08);border:1px solid rgba(38,166,154,0.25);"
            f'border-radius:6px;color:{UP};font-size:13px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{UP};'
            f'display:inline-block;"></span>{_esc(text)}</div>',
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
                td_style += _MONO
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
        f"border-radius:8px;background:{PANEL};"
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
    layout = dict(
        template="plotly_dark",
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="Inter, sans-serif", color=TEXT, size=12),
        margin=dict(l=48, r=24, t=36, b=40),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL,
            bordercolor=BORDER,
            font=dict(family="JetBrains Mono, monospace", color=TEXT, size=12),
        ),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_MUTED)),
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
    colors = [UP, ACCENT, WARN, TEXT_MUTED]
    for i, col in enumerate(y_cols):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[col],
            name=col,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy" if i == 0 else None,
            fillcolor="rgba(38,166,154,0.08)" if i == 0 else None,
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
        marker=dict(color=ACCENT),
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
        marker=dict(color=UP),
    ))
    fig.update_layout(**plotly_base_layout(title=title, height=height))
    st.plotly_chart(fig, use_container_width=True)
