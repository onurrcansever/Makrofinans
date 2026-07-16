# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from signal_engine.config.loader import SignalConfig
from signal_engine.data.bars import BarSeries, adx, ann_vol, sma


@dataclass
class RegimeResult:
    regime: str
    detail: str


def classify_regime(bars: BarSeries, cfg: SignalConfig) -> RegimeResult:
    c = bars.close
    if bars.bars < 60:
        return RegimeResult("RANGE_BOUND", "veri kısa")

    price = float(c.iloc[-1])
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    v30 = ann_vol(c, 30)
    v90 = ann_vol(c, 90)
    adx_val = adx(c, int(cfg.regime.get("adx_period", 14)))

    high_vol = False
    if v30 is not None:
        if v90 and v30 > v90 * cfg.regime.get("high_vol_ratio", 1.45):
            high_vol = True
        if v30 > cfg.regime.get("high_vol_abs_pct", 35.0):
            high_vol = True

    if high_vol:
        return RegimeResult("HIGH_VOL", f"vol30={v30:.0f}%")

    if s50 and s200 and price > s50 > s200:
        if adx_val and adx_val >= cfg.regime.get("adx_trend_min", 22):
            return RegimeResult("TRENDING_UP", f"ADX {adx_val:.0f}")
        return RegimeResult("TRENDING_UP", "SMA yapısı yukarı")

    if s50 and s200 and price < s50 < s200:
        return RegimeResult("TRENDING_DOWN", "SMA yapısı aşağı")

    return RegimeResult("RANGE_BOUND", "net trend yok")
