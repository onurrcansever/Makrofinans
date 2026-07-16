# -*- coding: utf-8 -*-
"""OHLCV yardımcıları — tek veri giriş noktası."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class BarSeries:
    close: pd.Series
    volume: Optional[pd.Series] = None
    bars: int = 0
    complete_1y: bool = False
    complete_2y: bool = False
    settlement_currency: str = ""
    quote_currency_raw: str = ""
    quarantine: bool = False
    quarantine_reason: str = ""

    @classmethod
    def from_series(
        cls,
        close: pd.Series,
        volume: Optional[pd.Series] = None,
        *,
        settlement_currency: str = "",
    ) -> "BarSeries":
        c = close.dropna().astype(float)
        v = volume.dropna().astype(float) if volume is not None else None
        n = len(c)
        return cls(
            close=c,
            volume=v,
            bars=n,
            complete_1y=n >= 252,
            complete_2y=n >= 504,
            settlement_currency=settlement_currency,
        )

    @classmethod
    def from_df(cls, df: pd.DataFrame, sembol: str) -> "BarSeries":
        from signal_engine.data.quote_normalize import (
            fetch_source_quote_currency,
            normalize_close_series,
        )

        raw = _extract_close(df, sembol)
        src = fetch_source_quote_currency(sembol) or None
        close, meta = normalize_close_series(sembol, raw, source_currency=src)
        if meta.quarantine:
            close = pd.Series(dtype=float)
        vol = _extract_volume(df, sembol)
        n = len(close)
        return cls(
            close=close,
            volume=vol if vol is not None and not vol.empty else None,
            bars=n,
            complete_1y=n >= 252,
            complete_2y=n >= 504,
            settlement_currency=meta.settlement_currency,
            quote_currency_raw=meta.quote_currency_raw,
            quarantine=meta.quarantine,
            quarantine_reason=meta.quarantine_reason or "",
        )


def _extract_close(df: pd.DataFrame, sembol: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sembol not in df.columns.get_level_values(0):
                return pd.Series(dtype=float)
            block = df[sembol]
            obj = block["Close"] if "Close" in block.columns else block.iloc[:, 0]
        else:
            obj = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        if isinstance(obj, pd.DataFrame):
            obj = obj.iloc[:, 0]
        return obj.dropna().astype(float)
    except Exception:
        return pd.Series(dtype=float)


def _extract_volume(df: pd.DataFrame, sembol: str) -> Optional[pd.Series]:
    if df.empty:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sembol not in df.columns.get_level_values(0):
                return None
            block = df[sembol]
            if "Volume" not in block.columns:
                return None
            return block["Volume"].dropna().astype(float)
        if "Volume" in df.columns:
            return df["Volume"].dropna().astype(float)
    except Exception:
        pass
    return None


def pct_change_n(close: pd.Series, n: int) -> Optional[float]:
    if len(close) < n + 1:
        return None
    eski, yeni = float(close.iloc[-n - 1]), float(close.iloc[-1])
    if eski <= 0:
        return None
    return (yeni / eski - 1.0) * 100.0


def pct_change_calendar(close: pd.Series, calendar_days: int = 365) -> Optional[float]:
    """Takvim günü penceresi — d1 − calendar_days, en yakın bar."""
    from fiyat_para_fx import fx_window_dates_calendar

    c = close.dropna().astype(float)
    if len(c) < 2:
        return None
    pair = fx_window_dates_calendar(c.index, calendar_days=calendar_days)
    if pair is None:
        return None
    d0, d1 = pair
    try:
        eski = float(c.loc[d0]) if d0 in c.index else float(c.asof(d0))
        yeni = float(c.loc[d1]) if d1 in c.index else float(c.iloc[-1])
    except Exception:
        return None
    if eski is None or yeni is None or eski <= 0 or pd.isna(eski) or pd.isna(yeni):
        return None
    return (yeni / eski - 1.0) * 100.0


def pct_change_window_info(close: pd.Series, n: int) -> Optional[dict]:
    """n-günlük getiri penceresinin başlangıç/bitiş tarihi, fiyat ve bar sayısı.

    n >= 252 → takvim 365g (1Y); aksi halde bar ofseti.
    """
    from fiyat_para_fx import fx_window_dates_calendar

    c = close.dropna().astype(float)
    if len(c) < 2:
        return None
    if n >= 252:
        pair = fx_window_dates_calendar(c.index, calendar_days=365)
        if pair is None:
            return None
        d0, d1 = pair
        eski = float(c.loc[d0]) if d0 in c.index else float(c.asof(d0))
        yeni = float(c.loc[d1]) if d1 in c.index else float(c.iloc[-1])
        if eski <= 0 or pd.isna(eski) or pd.isna(yeni):
            return None
        return {
            "n": n,
            "bar_count": len(c),
            "start_date": d0,
            "end_date": d1,
            "start_close": eski,
            "end_close": yeni,
            "return_pct": (yeni / eski - 1.0) * 100.0,
            "window": "calendar_365",
        }
    if len(c) < n + 1:
        return None
    i0, i1 = -n - 1, -1
    eski, yeni = float(c.iloc[i0]), float(c.iloc[i1])
    if eski <= 0:
        return None
    return {
        "n": n,
        "bar_count": len(c),
        "start_date": c.index[i0],
        "end_date": c.index[i1],
        "start_close": eski,
        "end_close": yeni,
        "return_pct": (yeni / eski - 1.0) * 100.0,
        "window": "bars",
    }


def sma(close: pd.Series, n: int) -> Optional[float]:
    if len(close) < n:
        return None
    return float(close.tail(n).mean())


def rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else np.inf
    return float(100 - (100 / (1 + rs)))


def bollinger_pct_b(close: pd.Series, n: int = 20, k: float = 2.0) -> Optional[float]:
    if len(close) < n:
        return None
    mid = close.tail(n).mean()
    std = close.tail(n).std()
    if std == 0 or pd.isna(std):
        return 0.5
    upper = mid + k * std
    lower = mid - k * std
    price = float(close.iloc[-1])
    if upper == lower:
        return 0.5
    return float((price - lower) / (upper - lower))


def drawdown_from_high(close: pd.Series, window: int = 252) -> Optional[float]:
    if len(close) < 20:
        return None
    seg = close.tail(min(window, len(close)))
    peak = float(seg.max())
    if peak <= 0:
        return None
    return (float(seg.iloc[-1]) / peak - 1.0) * 100.0


def ann_vol(close: pd.Series, days: int) -> Optional[float]:
    if len(close) < days + 5:
        return None
    rets = close.pct_change().dropna().tail(days)
    if len(rets) < max(10, days // 2):
        return None
    return float(rets.std() * np.sqrt(252) * 100)


def max_drawdown(close: pd.Series) -> Optional[float]:
    if len(close) < 20:
        return None
    cum = close / close.iloc[0]
    peak = cum.cummax()
    dd = (cum / peak - 1.0).min()
    return float(dd * 100)


def adx(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period * 3:
        return None
    high = close  # yfinance close-only proxy
    low = close
    tr = high.diff().abs()
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    val = dx.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def momentum_12_1(close: pd.Series) -> Optional[float]:
    """12 ay getiri, son 1 ay hariç (252-21 gün)."""
    if len(close) < 253:
        return None
    start = float(close.iloc[-253])
    end = float(close.iloc[-22])
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def truncate_bars_to_asof(bars: BarSeries, asof: pd.Timestamp) -> BarSeries:
    """Skor/faktör için — varlık barlarını ortak settlement asof'una kes."""
    if bars.close.empty:
        return bars
    asof = pd.Timestamp(asof)
    if bars.close.index[-1] <= asof:
        return bars
    c = bars.close.loc[bars.close.index <= asof]
    v = None
    if bars.volume is not None and not bars.volume.empty:
        v = bars.volume.loc[bars.volume.index <= asof]
    out = BarSeries.from_series(c, v, settlement_currency=bars.settlement_currency)
    out.quote_currency_raw = bars.quote_currency_raw
    out.quarantine = bars.quarantine
    out.quarantine_reason = bars.quarantine_reason
    return out


def settlement_asof(
    bars: BarSeries,
    bench: BarSeries,
    df: Optional[pd.DataFrame] = None,
) -> Optional[pd.Timestamp]:
    """Varlık + benchmark (+ gerekirse FX) için ortak son tamamlanmış gün.

    LSE bugün bar basmış, ^GSPC henüz yokken skorun tek taraflı kaymasını engeller.
    """
    if bars.close.empty or bench.close.empty:
        return None
    asof = min(pd.Timestamp(bars.close.index[-1]), pd.Timestamp(bench.close.index[-1]))
    asset_ccy = (bars.settlement_currency or "USD").upper()
    bench_ccy = (bench.settlement_currency or "USD").upper()
    if df is not None and asset_ccy != bench_ccy and asset_ccy in ("GBP", "EUR"):
        from signal_engine.data.fx_series import usd_per_unit

        fx = usd_per_unit(df, asset_ccy)
        if fx is not None and not fx.empty:
            asof = min(asof, pd.Timestamp(fx.index[-1]))
    return asof


def asset_class_for(h, cfg) -> str:
    sym = (h.sembol or "").upper()
    if h.piyasa == "ETF" or getattr(h, "varlik_turu", "") == "etf":
        broad = set(cfg.asset_classes.get("etf_broad") or [])
        if h.sektor in broad:
            return "etf_broad"
        return "etf_other"
    if sym.endswith(".IS"):
        return "bist"
    return "global_stock"


def benchmark_symbol(h, cfg) -> str:
    ac = asset_class_for(h, cfg)
    bm = cfg.benchmarks
    if ac == "bist":
        return bm.get("bist", "XU100.IS")
    if ac == "etf_broad" or ac == "etf_other":
        return bm.get("etf_global", "^GSPC")
    if h.piyasa == "NASDAQ":
        return bm.get("nasdaq", "^IXIC")
    return bm.get("us", "^GSPC")
