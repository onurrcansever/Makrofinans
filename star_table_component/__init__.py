# -*- coding: utf-8 -*-
"""
Favori yıldız tablosu — Streamlit Custom Component v1.

Yıldız HTML <tr> içinde (hizalama garantili).
JS → Python: Streamlit.setComponentValue({kind, i|id, t})
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import streamlit.components.v1 as components

_DIR = os.path.dirname(os.path.abspath(__file__))
_star_table = components.declare_component("star_favori_table", path=_DIR)


def star_favori_table(
    *,
    columns: List[str],
    rows: List[Dict[str, Any]],
    max_height: int = 480,
    has_action: bool = False,
    key: Optional[str] = None,
    default: Any = None,
) -> Any:
    """
    rows: [{filled: bool, cells: [{html|text, align, title}], action_id?, pad_px?}, ...]
    Dönüş: {kind: 'star'|'action', i|id, t} veya None.
    """
    return _star_table(
        columns=columns,
        rows=rows,
        max_height=int(max_height),
        has_action=bool(has_action),
        key=key,
        default=default,
    )


def build_star_rows_from_df(
    df,
    meta,
    *,
    store=None,
    favori_var_fn=None,
    pct_cols=None,
    badge_col: str = "Karar",
    row_ids=None,
    pad_px_by_row: Optional[List[int]] = None,
) -> tuple:
    """DataFrame → component rows (⭐ sütunu df'den düşülür)."""
    from ui_theme import _df_cell_align, _is_pct_col, format_df_cell_html

    if favori_var_fn is None:
        from favoriler import favori_var as favori_var_fn
    if store is None:
        from favoriler import yukle_store
        store = yukle_store()

    data = df.drop(columns=["⭐"], errors="ignore")
    cols = [str(c) for c in data.columns]
    pct_cols = pct_cols or {c for c in cols if _is_pct_col(c)}
    rows: List[Dict[str, Any]] = []
    for ri, (_, row) in enumerate(data.iterrows()):
        tur, sym, _ad = meta[ri] if ri < len(meta) else ("", "", "")
        filled = bool(favori_var_fn(store, tur, sym)) if tur else False
        cells = []
        for col in cols:
            val = row[col]
            align = "center" if col == "Sinyal" else _df_cell_align(col, val, pct_cols)
            if col == "Sinyal":
                from temel_veri import sinyal_tooltip

                skor_h = row["Skor"] if "Skor" in row.index else ""
                analist_var = any(
                    x in str(skor_h) for x in ("💚", "🟡", "🔴", "AL", "TUT", "SAT")
                )
                tip = sinyal_tooltip(
                    str(val).strip() if val is not None else "⏸",
                    analist_var=analist_var,
                )
            else:
                tip = "" if val is None else str(val)
            cells.append({
                "html": format_df_cell_html(col, val, pct_cols=pct_cols, badge_col=badge_col),
                "align": align,
                "title": tip,
                "text": "" if val is None else str(val),
            })
        entry: Dict[str, Any] = {"filled": filled, "cells": cells}
        if row_ids is not None and ri < len(row_ids):
            entry["action_id"] = str(row_ids[ri])
        if pad_px_by_row is not None and ri < len(pad_px_by_row):
            entry["pad_px"] = int(pad_px_by_row[ri])
        rows.append(entry)
    return cols, rows
