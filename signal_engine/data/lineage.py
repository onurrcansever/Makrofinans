# -*- coding: utf-8 -*-
"""Fiyat serisi soy ağacı — hangi kaynak / para birimi ile besleniyor."""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from signal_engine.data.bars import BarSeries, momentum_12_1, pct_change_n
from signal_engine.data.quote_normalize import (
    fetch_source_quote_currency,
    normalize_close_series,
    resolve_quote_currency,
)


def _extract_close(df: pd.DataFrame, sembol: str) -> pd.Series:
    from signal_engine.data.bars import _extract_close as _xc

    return _xc(df, sembol)


def trace_price_lineage(df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    """
    Sembol için fiyat hattını logla: Yahoo ham → quote currency → settlement → faktör girdisi.
    TL dönüşümü bu hatta yoktur; yalnızca GBp→GBP gibi settlement normalizasyonu uygulanır.
    """
    sym = (symbol or "").strip()
    raw = _extract_close(df, sym).dropna().astype(float)
    yahoo_ccy = fetch_source_quote_currency(sym)
    resolved_yaml = resolve_quote_currency(sym)
    resolved_src = resolve_quote_currency(sym, yahoo_ccy or None)
    norm_yaml, meta_yaml = normalize_close_series(sym, raw)
    norm_src, meta_src = normalize_close_series(sym, raw, source_currency=yahoo_ccy or None)
    bars = BarSeries.from_df(df, sym)

    out: Dict[str, Any] = {
        "symbol": sym,
        "yahoo_currency": yahoo_ccy or "—",
        "resolved_yaml_only": resolved_yaml,
        "resolved_with_yahoo": resolved_src,
        "settlement_currency": meta_src.settlement_currency,
        "engine_settlement": bars.settlement_currency,
        "quarantine": meta_src.quarantine,
        "quarantine_reason": meta_src.quarantine_reason or "",
        "yaml_vs_yahoo_mismatch": resolved_yaml != resolved_src,
        "normalization_divergence": (
            not norm_yaml.empty
            and not norm_src.empty
            and abs(float(norm_yaml.iloc[-1]) - float(norm_src.iloc[-1])) > 1e-6
        ),
    }
    if not raw.empty:
        out["raw_last"] = round(float(raw.iloc[-1]), 4)
        out["raw_median_200"] = round(float(raw.tail(min(200, len(raw))).median()), 4)
    if not norm_src.empty:
        out["settlement_last"] = round(float(norm_src.iloc[-1]), 4)
        out["settlement_median_200"] = round(float(norm_src.tail(min(200, len(norm_src))).median()), 4)
        mom = momentum_12_1(norm_src)
        out["momentum_12_1_settlement_pct"] = round(mom, 2) if mom is not None else None
        d1y = pct_change_n(norm_src, 252)
        d1a = pct_change_n(norm_src, 21)
        out["return_1y_settlement_pct"] = round(d1y, 2) if d1y is not None else None
        out["return_1a_settlement_pct"] = round(d1a, 2) if d1a is not None else None
    out["bars_count"] = bars.bars
    return out


def log_price_lineage(df: pd.DataFrame, symbols: list[str]) -> None:
    """Geliştirici tanısı — stdout'a soy ağacı yazar."""
    for sym in symbols:
        info = trace_price_lineage(df, sym)
        print(f"[lineage] {sym}: settlement={info.get('settlement_currency')} "
              f"yahoo={info.get('yahoo_currency')} "
              f"12-1M={info.get('momentum_12_1_settlement_pct')}% "
              f"quarantine={info.get('quarantine')}")
