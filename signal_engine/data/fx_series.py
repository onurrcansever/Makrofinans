# -*- coding: utf-8 -*-
"""Benchmark ve varlık serileri arasında settlement PB hizalaması."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from signal_engine.data.bars import _extract_close

# Yahoo: USD cinsinden 1 birim yabancı para (EURUSD=X → USD/EUR, GBPUSD=X → USD/GBP).
_FX_SYMBOL = {
    "GBP": "GBPUSD=X",
    "EUR": "EURUSD=X",
}

_BENCH_SETTLEMENT = {
    "^GSPC": "USD",
    "^IXIC": "USD",
    "^NDX": "USD",
    "XU100.IS": "TL",
}


def benchmark_settlement(bench_symbol: str) -> str:
    return _BENCH_SETTLEMENT.get(bench_symbol.upper(), "USD")


def usd_per_unit(df: pd.DataFrame, currency: str) -> Optional[pd.Series]:
    """1 birim `currency` kaç USD — Yahoo FX sembollerinden."""
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return None
    sym = _FX_SYMBOL.get(ccy)
    if not sym:
        return None
    s = _extract_close(df, sym)
    if s is None or s.empty:
        return None
    return s.astype(float)


def benchmark_close_in_settlement(
    bench_close: pd.Series,
    asset_settlement: str,
    df: pd.DataFrame,
    *,
    bench_settlement: str = "USD",
) -> pd.Series:
    """
    Benchmark kapanışlarını varlığın settlement PB'sine çevirir.

    Örn. ^GSPC (USD) → EQQQ.L (GBP): bench_gbp[t] = bench_usd[t] / GBPUSD[t]

    FX yoksa sessizce ham bench DÖNMEZ — boş seri (RS unavailable).
    """
    from fiyat_para_fx import FxUnavailableError

    asset_ccy = (asset_settlement or "USD").upper()
    bench_ccy = (bench_settlement or "USD").upper()
    if asset_ccy == bench_ccy:
        return bench_close.astype(float)

    if bench_ccy != "USD":
        raise FxUnavailableError(
            f"benchmark_close_in_settlement: bench={bench_ccy} henüz desteklenmiyor "
            f"(asset={asset_ccy})"
        )

    fx = usd_per_unit(df, asset_ccy)
    if fx is None or fx.empty:
        raise FxUnavailableError(
            f"benchmark_close_in_settlement: {asset_ccy} FX serisi yok — "
            "unconverted bench yasak (yanlış α)"
        )

    # Bench takvimi dışındaki canlı FX günü ffill ile sızmasın
    bench_end = pd.Timestamp(bench_close.index[-1])
    fx = fx.loc[fx.index <= bench_end]
    if fx.empty:
        raise FxUnavailableError(
            f"benchmark_close_in_settlement: {asset_ccy} FX bench asof sonrası boş"
        )

    aligned = fx.reindex(bench_close.index, method="ffill")
    out = bench_close.astype(float) / aligned
    return out.dropna(how="all")
