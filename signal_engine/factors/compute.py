# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from signal_engine.data.bars import (
    BarSeries,
    ann_vol,
    bollinger_pct_b,
    drawdown_from_high,
    momentum_12_1,
    pct_change_n,
    rsi,
    sma,
)


@dataclass
class FactorResult:
    score: float
    available: bool
    detail: str = ""


def _clip_score(x: float) -> float:
    return max(0.0, min(100.0, x))


def trend_factor(bars: BarSeries) -> FactorResult:
    c = bars.close
    if bars.bars < 60:
        return FactorResult(50.0, False, "yetersiz bar")
    price = float(c.iloc[-1])
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    mom = momentum_12_1(c)
    parts = []
    score = 50.0
    if s50 and s200:
        if price > s50 > s200:
            score += 22
            parts.append("SMA50>SMA200")
        elif price > s50:
            score += 10
        elif price < s50 < s200:
            score -= 18
            parts.append("downtrend")
    if len(c) >= 70:
        s50_old = float(c.iloc[-70:-20].mean()) if len(c) >= 70 else None
        if s50 and s50_old and s50_old > 0:
            slope = (s50 / s50_old - 1) * 100
            score += max(-10, min(10, slope * 2))
            parts.append(f"slope {slope:+.1f}%")
    if mom is not None:
        if mom > 15:
            score += 15
        elif mom > 5:
            score += 8
        elif mom < -5:
            score -= 10
        ccy = (bars.settlement_currency or "").strip()
        mom_lbl = f"12-1M {mom:+.0f}%"
        if ccy:
            mom_lbl += f" ({ccy})"
        parts.append(mom_lbl)
    return FactorResult(_clip_score(score), True, "; ".join(parts))


def mean_reversion_factor(bars: BarSeries) -> FactorResult:
    c = bars.close
    if bars.bars < 30:
        return FactorResult(50.0, False, "yetersiz bar")
    r = rsi(c, 14)
    bb = bollinger_pct_b(c, 20, 2.0)
    dd = drawdown_from_high(c, 252)
    score = 50.0
    parts = []
    if r is not None:
        if r <= 35:
            score += 18
        elif r <= 45:
            score += 8
        elif r >= 70:
            score -= 18
        elif r >= 60:
            score -= 8
        parts.append(f"RSI(14) {r:.0f}")
    if bb is not None:
        if bb < 0.2:
            score += 10
        elif bb > 0.85:
            score -= 12
        parts.append(f"BB %B {bb:.2f}")
    if dd is not None:
        if dd <= -15:
            score += 8
        elif dd >= -3:
            score -= 10
        parts.append(f"52H {dd:+.0f}%")
    return FactorResult(_clip_score(score), True, "; ".join(parts))


def volatility_factor(bars: BarSeries, risk_limit: float = 32.0) -> FactorResult:
    c = bars.close
    v30 = ann_vol(c, 30)
    v90 = ann_vol(c, 90)
    mdd = max_drawdown_local(c)
    if v30 is None:
        return FactorResult(50.0, False, "vol yok")
    score = 50.0
    parts = [f"vol30 {v30:.0f}%"]
    if v30 <= risk_limit:
        score += 15
    elif v30 >= risk_limit * 1.4:
        score -= 20
    else:
        score -= 5
    if v90 and v30 > v90 * 1.45:
        score -= 12
        parts.append("vol spike")
    if mdd is not None and mdd < -25:
        score -= 8
        parts.append(f"MDD {mdd:.0f}%")
    return FactorResult(_clip_score(score), True, "; ".join(parts))


def max_drawdown_local(close: pd.Series):
    from signal_engine.data.bars import max_drawdown
    return max_drawdown(close)


def relative_strength_factor(
    bars: BarSeries,
    bench: BarSeries,
    *,
    df: Optional[pd.DataFrame] = None,
    bench_symbol: str = "",
) -> FactorResult:
    if bars.bars < 63 or bench.bars < 63:
        return FactorResult(50.0, False, "bench yok")

    from signal_engine.data.fx_series import benchmark_close_in_settlement, benchmark_settlement

    asset_ccy = bars.settlement_currency or "USD"
    bench_ccy = benchmark_settlement(bench_symbol) if bench_symbol else "USD"
    bench_close = bench.close
    if df is not None and asset_ccy != bench_ccy:
        try:
            bench_close = benchmark_close_in_settlement(
                bench.close, asset_ccy, df, bench_settlement=bench_ccy,
            )
        except Exception as exc:
            from fiyat_para_fx import FxUnavailableError
            if isinstance(exc, FxUnavailableError):
                return FactorResult(50.0, False, f"FX yok ({exc})")
            raise
    bench_aligned = bench_close.reindex(bars.close.index, method="ffill")

    r3 = pct_change_n(bars.close, 63)
    b3 = pct_change_n(bench_aligned, 63)
    r6 = pct_change_n(bars.close, 126) if bars.bars >= 127 else None
    b6 = pct_change_n(bench_aligned, 126) if len(bench_aligned) >= 127 else None
    score = 50.0
    parts = []
    if r3 is not None and b3 is not None:
        diff = r3 - b3
        score += max(-15, min(15, diff / 2))
        parts.append(f"3M α {diff:+.2f}pp")
    if r6 is not None and b6 is not None:
        diff6 = r6 - b6
        score += max(-10, min(10, diff6 / 3))
        parts.append(f"6M α {diff6:+.2f}pp")
    avail = r3 is not None and b3 is not None
    return FactorResult(_clip_score(score), avail, "; ".join(parts))


def liquidity_factor(
    bars: BarSeries,
    *,
    isin: str = "",
    etf_meta: Optional[dict] = None,
) -> FactorResult:
    from signal_engine.data.etf_quality import etf_meta as _etf_meta

    meta = etf_meta or _etf_meta(isin)
    vol_part = 50.0
    vol_ok = False
    if bars.volume is not None and len(bars.volume) >= 40:
        v20 = float(bars.volume.tail(20).mean())
        v60 = float(bars.volume.tail(60).mean())
        if v60 > 0:
            vol_ok = True
            ratio = v20 / v60
            vol_part = 50.0
            if ratio > 1.15:
                vol_part += 15
            elif ratio > 0.85:
                vol_part += 5
            else:
                vol_part -= 8
            vol_detail = f"hacim {ratio:.2f}"
        else:
            vol_detail = "hacim 0"
    else:
        vol_detail = "hacim yok"

    if meta:
        aum = float(meta.get("aum_bn_eur") or 0)
        ter = float(meta.get("ter_pct") or 0.5)
        q = 50.0
        if aum >= 10:
            q += 18
        elif aum >= 3:
            q += 10
        elif aum >= 1:
            q += 4
        if ter <= 0.10:
            q += 12
        elif ter <= 0.20:
            q += 6
        elif ter >= 0.35:
            q -= 8
        score = _clip_score((vol_part + q) / 2 if vol_ok else q)
        detail = f"AUM ~{aum:.0f}bn EUR · TER {ter:.2f}% · {vol_detail}"
        return FactorResult(score, True, detail)

    if not vol_ok:
        return FactorResult(55.0, False, vol_detail)
    return FactorResult(_clip_score(vol_part), True, vol_detail)
