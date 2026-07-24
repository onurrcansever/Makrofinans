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


# Backtest / flag için hazır presets (yaml ile override edilebilir)
_SHORT_MOM_PRESETS = {
    "small": {
        "m1_hi": (8.0, 6.0),
        "m1_mid": (3.0, 3.0),
        "m1_lo": (-5.0, -4.0),
        "m3_hi": (12.0, 5.0),
        "m3_mid": (5.0, 2.0),
        "m3_lo": (-8.0, -4.0),
    },
    "temkinli": {
        "m1_hi": (8.0, 2.0),
        "m1_mid": (3.0, 1.0),
        "m1_lo": (-5.0, -2.0),
        "m3_hi": (12.0, 6.0),
        "m3_mid": (5.0, 3.0),
        "m3_lo": (-8.0, -4.0),
    },
    # Claude önerisi: +4 ile whipsaw baskısını düşür, upgrade'in bir kısmını koru
    "siki": {
        "m1_hi": (8.0, 2.0),
        "m1_mid": (3.0, 1.0),
        "m1_lo": (-5.0, -2.0),
        "m3_hi": (12.0, 4.0),
        "m3_mid": (5.0, 2.0),
        "m3_lo": (-8.0, -3.0),
    },
}


def _pair(raw, default: tuple) -> tuple:
    if raw is None:
        return default
    try:
        return (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError, IndexError):
        return default


def resolve_short_mom_preset(
    preset: Optional[str] = None,
    *,
    cfg_block: Optional[dict] = None,
) -> Optional[dict]:
    """None = kısa mom kapalı. cfg_block = signal_config.short_momentum."""
    block = cfg_block or {}
    name = (preset if preset is not None else block.get("preset")) or "temkinli"
    name = str(name).strip().lower()
    if name in ("off", "none", ""):
        return None
    base = dict(_SHORT_MOM_PRESETS.get(name) or _SHORT_MOM_PRESETS["temkinli"])
    overrides = (block.get("presets") or {}).get(name) or {}
    out = {}
    for k, default in base.items():
        out[k] = _pair(overrides.get(k), default if isinstance(default, tuple) else tuple(default))
    return out


def short_mom_adjustment(close: pd.Series, preset: dict) -> tuple:
    """(puan, detay). 1A/3A pct_change ile küçük bonus/ceza."""
    if not preset:
        return 0.0, ""
    adj = 0.0
    parts = []
    m1 = pct_change_n(close, 21)
    m3 = pct_change_n(close, 63)
    if m1 is not None:
        hi, mid, lo = preset["m1_hi"], preset["m1_mid"], preset["m1_lo"]
        if m1 > hi[0]:
            adj += hi[1]
            parts.append(f"1A {m1:+.0f}%→{hi[1]:+.0f}")
        elif m1 > mid[0]:
            adj += mid[1]
            parts.append(f"1A {m1:+.0f}%→{mid[1]:+.0f}")
        elif m1 < lo[0]:
            adj += lo[1]
            parts.append(f"1A {m1:+.0f}%→{lo[1]:+.0f}")
    if m3 is not None:
        hi, mid, lo = preset["m3_hi"], preset["m3_mid"], preset["m3_lo"]
        if m3 > hi[0]:
            adj += hi[1]
            parts.append(f"3A {m3:+.0f}%→{hi[1]:+.0f}")
        elif m3 > mid[0]:
            adj += mid[1]
            parts.append(f"3A {m3:+.0f}%→{mid[1]:+.0f}")
        elif m3 < lo[0]:
            adj += lo[1]
            parts.append(f"3A {m3:+.0f}%→{lo[1]:+.0f}")
    return adj, "; ".join(parts)


def trend_factor(
    bars: BarSeries,
    *,
    short_mom_preset: Optional[str] = None,
    short_mom_cfg: Optional[dict] = None,
    apply_short_mom: Optional[bool] = None,
) -> FactorResult:
    """Trend faktörü. Kısa mom: apply_short_mom=True veya cfg.enabled; preset ile A/B."""
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

    cfg_block = short_mom_cfg
    if cfg_block is None:
        try:
            from signal_engine.config.loader import load_signal_config
            cfg_block = load_signal_config().short_momentum or {}
        except Exception:
            cfg_block = {}
    use = apply_short_mom
    if use is None:
        use = bool(cfg_block.get("enabled"))
    if use:
        preset = resolve_short_mom_preset(short_mom_preset, cfg_block=cfg_block)
        if preset:
            adj, det = short_mom_adjustment(c, preset)
            if adj:
                score += adj
            if det:
                parts.append(det)

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
