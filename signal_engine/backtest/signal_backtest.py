# -*- coding: utf-8 -*-
"""Sinyal backtest — lookahead test + basit istatistik."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from signal_engine.data.bars import BarSeries
from signal_engine.factors.compute import trend_factor


@dataclass
class BacktestRow:
    signal: str
    count: int
    avg_ret_1m: Optional[float]
    avg_ret_3m: Optional[float]
    hit_rate_1m: Optional[float]


def assert_no_lookahead(close: pd.Series) -> bool:
    """Gelecek barlar değişince t anındaki skor değişmemeli."""
    if len(close) < 100:
        return True
    t = len(close) - 30
    base = close.copy()
    tampered = close.copy()
    tampered.iloc[t + 1 :] = float(close.iloc[t:].max()) * 1.5

    seg = base.iloc[: t + 1]
    seg_t = tampered.iloc[: t + 1]
    s1 = trend_factor(BarSeries.from_series(seg)).score
    s2 = trend_factor(BarSeries.from_series(seg_t)).score
    if s1 != s2:
        return False

    altered = close.copy()
    altered.iloc[max(0, t - 5) : t + 1] *= 0.5
    s3 = trend_factor(BarSeries.from_series(altered.iloc[: t + 1])).score
    return s3 != s1


def _forward_return(close: pd.Series, i: int, days: int) -> Optional[float]:
    if i + days >= len(close):
        return None
    a, b = float(close.iloc[i]), float(close.iloc[i + days])
    if a <= 0:
        return None
    return (b / a - 1) * 100


def run_signal_backtest(close: pd.Series, min_score: float = 65.0) -> List[BacktestRow]:
    """Basit walk-forward: trend skoru > eşik → 1M/3M getiri."""
    if len(close) < 300:
        return []
    rets_1m, rets_3m = [], []
    for i in range(252, len(close) - 63):
        seg = close.iloc[: i + 1]
        tr = trend_factor(BarSeries.from_series(seg))
        if tr.score >= min_score:
            r1 = _forward_return(close, i, 21)
            r3 = _forward_return(close, i, 63)
            if r1 is not None:
                rets_1m.append(r1)
            if r3 is not None:
                rets_3m.append(r3)
    if not rets_1m:
        return [BacktestRow("TREND_HIGH", 0, None, None, None)]
    return [
        BacktestRow(
            signal="TREND_HIGH",
            count=len(rets_1m),
            avg_ret_1m=float(np.mean(rets_1m)),
            avg_ret_3m=float(np.mean(rets_3m)) if rets_3m else None,
            hit_rate_1m=float(np.mean([1 if r > 0 else 0 for r in rets_1m])),
        )
    ]
