# -*- coding: utf-8 -*-
"""Ichimoku bulutu — kural tabanlı alım bölgesi (kehanet değil).

OHLC yoksa close üzerinden mid-line (rolling max/min of close) kullanılır.
buy_zone: «buradan alınabilir bölge» — bulut desteği / TK bullish + aşırı uzatmama.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from signal_engine.data.bars import BarSeries

TENKAN_N = 9
KIJUN_N = 26
SENKOU_B_N = 52
CLOUD_NEAR_PCT = 0.02
OVEREXTENDED_PCT = 0.08


@dataclass
class IchimokuZone:
    tenkan: Optional[float] = None
    kijun: Optional[float] = None
    senkou_a: Optional[float] = None
    senkou_b: Optional[float] = None
    cloud_top: Optional[float] = None
    cloud_bottom: Optional[float] = None
    price: Optional[float] = None
    price_above_cloud: bool = False
    price_below_cloud: bool = False
    in_or_near_cloud: bool = False
    bullish_tk_cross: bool = False
    overextended: bool = False
    buy_zone: bool = False
    note: str = ""
    bars_used: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _mid_hl(high: pd.Series, low: pd.Series, n: int) -> pd.Series:
    return (high.rolling(n).max() + low.rolling(n).min()) / 2.0


def compute_ichimoku_zone(
    bars: BarSeries,
    *,
    high: Optional[pd.Series] = None,
    low: Optional[pd.Series] = None,
    near_pct: float = CLOUD_NEAR_PCT,
    overextend_pct: float = OVEREXTENDED_PCT,
) -> IchimokuZone:
    """Son bar için Ichimoku özeti + buy_zone bayrağı."""
    c = bars.close
    n = len(c)
    out = IchimokuZone(bars_used=n)
    need = SENKOU_B_N + KIJUN_N + 2
    if n < need:
        out.note = f"Ichimoku için yetersiz bar ({n}<{need})"
        return out

    if high is None or low is None or len(high) < n or len(low) < n:
        high = c
        low = c
    else:
        high = high.reindex(c.index).ffill()
        low = low.reindex(c.index).ffill()

    tenkan_s = _mid_hl(high, low, TENKAN_N)
    kijun_s = _mid_hl(high, low, KIJUN_N)
    span_a = ((tenkan_s + kijun_s) / 2.0).shift(KIJUN_N)
    span_b = _mid_hl(high, low, SENKOU_B_N).shift(KIJUN_N)

    price = float(c.iloc[-1])
    t = float(tenkan_s.iloc[-1]) if pd.notna(tenkan_s.iloc[-1]) else None
    k = float(kijun_s.iloc[-1]) if pd.notna(kijun_s.iloc[-1]) else None
    sa = float(span_a.iloc[-1]) if pd.notna(span_a.iloc[-1]) else None
    sb = float(span_b.iloc[-1]) if pd.notna(span_b.iloc[-1]) else None

    out.price = price
    out.tenkan = t
    out.kijun = k
    out.senkou_a = sa
    out.senkou_b = sb

    if sa is None or sb is None:
        out.note = "Ichimoku bulut eksik"
        return out

    cloud_top = max(sa, sb)
    cloud_bot = min(sa, sb)
    out.cloud_top = cloud_top
    out.cloud_bottom = cloud_bot

    out.price_above_cloud = price > cloud_top
    out.price_below_cloud = price < cloud_bot
    in_cloud = cloud_bot <= price <= cloud_top
    near_above = abs(price / cloud_top - 1.0) <= near_pct
    near_below = abs(price / cloud_bot - 1.0) <= near_pct
    out.in_or_near_cloud = bool(in_cloud or near_above or near_below)

    bullish_cross = False
    for i in range(-3, 0):
        t0, t1 = tenkan_s.iloc[i - 1], tenkan_s.iloc[i]
        k0, k1 = kijun_s.iloc[i - 1], kijun_s.iloc[i]
        if pd.isna(t0) or pd.isna(t1) or pd.isna(k0) or pd.isna(k1):
            continue
        if float(t0) <= float(k0) and float(t1) > float(k1):
            bullish_cross = True
            break
    out.bullish_tk_cross = bullish_cross

    out.overextended = bool(
        out.price_above_cloud and (price / cloud_top - 1.0) >= overextend_pct
    )

    support_touch = out.in_or_near_cloud and not out.price_below_cloud
    momentum_ok = bullish_cross and (out.price_above_cloud or out.in_or_near_cloud)
    out.buy_zone = bool(
        not out.overextended
        and not out.price_below_cloud
        and (support_touch or momentum_ok)
    )

    if out.buy_zone:
        parts = []
        if support_touch:
            parts.append("bulut desteği/kenarı")
        if bullish_cross:
            parts.append("TK bullish kesişim")
        out.note = "Ichimoku alım bölgesi: " + ", ".join(parts)
    elif out.overextended:
        out.note = "Ichimoku: bulut üstü aşırı uzatma — bölge kapalı"
    elif out.price_below_cloud:
        out.note = "Ichimoku: fiyat bulut altında"
    else:
        out.note = "Ichimoku: alım bölgesi yok"

    return out
