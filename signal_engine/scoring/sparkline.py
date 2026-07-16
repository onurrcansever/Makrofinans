# -*- coding: utf-8 -*-
"""90 günlük skor sparkline — haftalık örnekleme."""
from __future__ import annotations

from typing import List

from signal_engine.config.loader import SignalConfig
from signal_engine.data.bars import BarSeries
from signal_engine.factors.compute import (
    mean_reversion_factor,
    relative_strength_factor,
    trend_factor,
    volatility_factor,
    liquidity_factor,
)
from signal_engine.scoring.composite import composite_score


def compute_score_sparkline(
    bars: BarSeries,
    bench: BarSeries,
    cfg: SignalConfig,
    *,
    risk_limit: float = 32.0,
    weeks: int = 13,
) -> List[float]:
    """Son ~90 günde haftalık bileşik skor (hafif, 3 faktör)."""
    c = bars.close
    if len(c) < 80:
        return []
    out: List[float] = []
    step = 7
    for w in range(weeks, 0, -1):
        end = len(c) - (w - 1) * step
        if end < 60:
            continue
        seg = c.iloc[:end]
        bseg = bench.close.iloc[: min(end, len(bench.close))]
        sb = BarSeries.from_series(seg)
        bb = BarSeries.from_series(bseg)
        factors = {
            "trend": trend_factor(sb),
            "mean_reversion": mean_reversion_factor(sb),
            "volatility": volatility_factor(sb, risk_limit=risk_limit),
            "relative_strength": relative_strength_factor(sb, bb),
            "liquidity": liquidity_factor(sb),
        }
        score, _, _ = composite_score(factors, cfg)
        out.append(round(score, 1))
    return out[-weeks:]
