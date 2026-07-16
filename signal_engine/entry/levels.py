# -*- coding: utf-8
"""Structure-based entry levels — primary + secondary with distinct P(fill)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from signal_engine.config.loader import SignalConfig
from signal_engine.data.bars import BarSeries, drawdown_from_high, sma

SPOT_NEAR_PCT = 0.02
ENTRY_SANITY_PCT = 0.15


class EntrySanityError(ValueError):
    """Al seviyesi spot'tan aşırı sapmış — sinyal üretilmez."""


@dataclass
class EntryLevel:
    price: Optional[float]
    method: str
    p_fill_90d: Optional[float]
    dca_preferred: bool
    note: str = ""
    secondary_price: Optional[float] = None
    secondary_method: str = ""
    secondary_p_fill: Optional[float] = None
    spot_near: bool = False
    settlement_currency: str = ""
    spot_distance_pct: Optional[float] = None


def _high_52(close: pd.Series) -> Optional[float]:
    if len(close) < 20:
        return None
    return float(close.tail(min(252, len(close))).max())


def _swing_low_cluster(close: pd.Series, lookback: int = 60) -> Optional[float]:
    """Recent swing-low cluster — min of local minima in window."""
    seg = close.tail(lookback)
    if len(seg) < 15:
        return None
    lows: List[float] = []
    arr = seg.values.astype(float)
    for i in range(2, len(arr) - 2):
        if arr[i] <= arr[i - 1] and arr[i] <= arr[i + 1]:
            lows.append(float(arr[i]))
    if not lows:
        return float(seg.min())
    return float(np.median(lows[-5:])) if len(lows) >= 3 else float(min(lows))


def historical_p_fill(close: pd.Series, target: float, horizon: int = 90) -> Optional[float]:
    """Tarihsel dokunma oranı — limit doldurma olasılığı DEĞİL.

    Formül: son ~5y içinde her gün i için
      hit_i = 1{ min(close[i+1 .. i+horizon]) <= target }
      P = mean(hit_i)

    target == bugünkü spot olsa bile %100 dönmez: geçmişteki her pencerede
    fiyatın o mutlak seviyeye inip inmediğini sayar (seviyenin tarihsel
    konumuna bağlı). DCA / karar için KULLANILMAZ — bkz. compute_entry.
    """
    if len(close) < horizon + 60 or target <= 0:
        return None
    arr = close.values.astype(float)
    hits = 0
    total = 0
    start = max(0, len(arr) - min(len(arr), 1260) - horizon)
    for i in range(start, len(arr) - horizon - 1):
        window = arr[i + 1 : i + 1 + horizon]
        if len(window) < horizon // 2:
            continue
        total += 1
        if np.min(window) <= target:
            hits += 1
    if total < 30:
        return None
    return hits / total


def _pick_primary_secondary(
    price: float,
    cands: List[Tuple[float, str]],
) -> Tuple[Optional[float], str, Optional[float], str]:
    """Higher structural level = primary; deeper = secondary."""
    valid = [(p, m) for p, m in cands if p and 0 < p < price * 0.998]
    if not valid:
        return None, "—", None, ""
    valid.sort(key=lambda x: -x[0])
    p1, m1 = valid[0]
    p2, m2 = (valid[1] if len(valid) > 1 else (None, ""))
    if p2 and p2 >= p1 * 0.995:
        p2, m2 = None, ""
    return p1, m1, p2, m2


def compute_entry(bars: BarSeries, regime: str, cfg: SignalConfig) -> EntryLevel:
    c = bars.close
    if bars.bars < 30:
        return EntryLevel(None, "—", None, False, "veri yok")

    price = float(c.iloc[-1])
    s20 = sma(c, 20)
    s50 = sma(c, 50)
    high = _high_52(c)
    swing = _swing_low_cluster(c)
    dd = drawdown_from_high(c, 252)
    ent = cfg.entry

    cands: List[Tuple[float, str]] = []
    if s20:
        cands.append((s20, "SMA20"))
    if swing:
        cands.append((swing, "swing-low"))
    if s50:
        cands.append((s50, "SMA50"))
    if regime in ("TRENDING_DOWN", "HIGH_VOL") and high:
        cands.append((high * float(ent.get("deep_52h_pct", 0.88)), "52H derin"))
    elif regime == "RANGE_BOUND" and s50:
        cands.append((s50 * 0.97, "SMA50 alt band"))

    primary, method, secondary, sec_method = _pick_primary_secondary(price, cands)

    if primary is None:
        primary = price * 0.95
        method = "−5% contingency"

    dist = abs(primary / price - 1.0) if price > 0 else 1.0
    if dist > ENTRY_SANITY_PCT:
        raise EntrySanityError(
            f"Al seviyesi spot'tan %{dist * 100:.1f} uzak "
            f"({primary:.4f} vs {price:.4f} {bars.settlement_currency or ''})"
        )

    spot_near = dist <= SPOT_NEAR_PCT
    display_method = method
    note = ""
    if spot_near:
        display_method = f"{method} · spot civarı"
        note = (
            f"Spot'a %{dist * 100:.1f} mesafe — piyasa/limit spot civarı; "
            "daha derin hedef için ikincil seviyeye bakın"
        )
    elif regime == "TRENDING_UP" and dd is not None and dd > -5:
        note = "Yükselen trend — yapısal geri çekilme"

    # historical_p_fill / DCA ayrıldı — bozuk dokunma oranı karar vermez.
    return EntryLevel(
        price=round(float(primary), 4),
        method=display_method,
        p_fill_90d=None,
        dca_preferred=False,
        note=note,
        secondary_price=round(float(secondary), 4) if secondary else None,
        secondary_method=sec_method,
        secondary_p_fill=None,
        spot_near=spot_near,
        settlement_currency=bars.settlement_currency or "",
        spot_distance_pct=round(dist * 100, 2),
    )
