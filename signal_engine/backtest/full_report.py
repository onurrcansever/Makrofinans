# -*- coding: utf-8 -*-
"""5Y vektörize sinyal backtest raporu."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from signal_engine.config.loader import load_signal_config
from signal_engine.data.bars import BarSeries
from signal_engine.factors.compute import trend_factor
from signal_engine.scoring.composite import composite_score
from signal_engine.factors.compute import (
    FactorResult,
    mean_reversion_factor,
    relative_strength_factor,
    volatility_factor,
    liquidity_factor,
)

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_SYMBOLS = ["CSPX.L", "VWCE.DE", "VUSA.L", "AAPL", "ASELS.IS"]


@dataclass
class SymbolReport:
    sembol: str
    bars: int
    signal_count: int
    avg_ret_1m: Optional[float]
    avg_ret_3m: Optional[float]
    avg_ret_6m: Optional[float]
    hit_rate_1m: Optional[float]
    buy_hold_1y: Optional[float]
    sharpe_signal: Optional[float]


@dataclass
class BacktestReport:
    generated_at: str
    config_hash: str
    symbols: List[SymbolReport] = field(default_factory=list)
    lookahead_ok: bool = True
    notes: str = ""


def _config_hash() -> str:
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "signal_config.yaml"
    return hashlib.sha256(cfg_path.read_bytes()).hexdigest()[:16]


def _download(symbols: List[str], period: str = "5y") -> pd.DataFrame:
    import yfinance as yf
    return yf.download(
        symbols, period=period, group_by="ticker", auto_adjust=True, progress=False, threads=True,
    )


def _close(df: pd.DataFrame, sym: str) -> pd.Series:
    return BarSeries.from_df(df, sym).close


def _walk_forward(close: pd.Series, bench: pd.Series, min_score: float = 65.0) -> SymbolReport:
    cfg = load_signal_config()
    rets_1m, rets_3m, rets_6m = [], [], []
    for i in range(252, len(close) - 126):
        seg = close.iloc[: i + 1]
        bseg = bench.iloc[: min(i + 1, len(bench))]
        sb = BarSeries.from_series(seg)
        bb = BarSeries.from_series(bseg)
        factors = {
            "trend": trend_factor(sb),
            "mean_reversion": mean_reversion_factor(sb),
            "volatility": volatility_factor(sb),
            "relative_strength": relative_strength_factor(sb, bb),
            "liquidity": liquidity_factor(sb),
        }
        score, _, _ = composite_score(factors, cfg)
        if score < min_score:
            continue
        for days, bucket in ((21, rets_1m), (63, rets_3m), (126, rets_6m)):
            if i + days < len(close):
                a, b = float(close.iloc[i]), float(close.iloc[i + days])
                if a > 0:
                    bucket.append((b / a - 1) * 100)

    def _avg(xs):
        return float(np.mean(xs)) if xs else None

    def _hit(xs):
        return float(np.mean([1 if x > 0 else 0 for x in xs])) if xs else None

    bh = None
    if len(close) >= 252:
        bh = (float(close.iloc[-1]) / float(close.iloc[-252]) - 1) * 100

    sig_rets = rets_1m
    sharpe = None
    if len(sig_rets) >= 5:
        sharpe = float(np.mean(sig_rets) / (np.std(sig_rets) + 1e-9) * np.sqrt(12))

    return SymbolReport(
        sembol="",
        bars=len(close),
        signal_count=len(rets_1m),
        avg_ret_1m=_avg(rets_1m),
        avg_ret_3m=_avg(rets_3m),
        avg_ret_6m=_avg(rets_6m),
        hit_rate_1m=_hit(rets_1m),
        buy_hold_1y=bh,
        sharpe_signal=sharpe,
    )


def generate_report(
    symbols: Optional[List[str]] = None,
    *,
    period: str = "5y",
) -> BacktestReport:
    from signal_engine.backtest.signal_backtest import assert_no_lookahead

    symbols = symbols or DEFAULT_SYMBOLS
    df = _download(symbols + ["^GSPC"], period=period)
    bench = _close(df, "^GSPC")
    rows: List[SymbolReport] = []
    la_ok = True
    for sym in symbols:
        close = _close(df, sym)
        if len(close) < 300:
            rows.append(SymbolReport(sembol=sym, bars=len(close), signal_count=0,
                                     avg_ret_1m=None, avg_ret_3m=None, avg_ret_6m=None,
                                     hit_rate_1m=None, buy_hold_1y=None, sharpe_signal=None))
            continue
        la_ok = la_ok and assert_no_lookahead(close)
        rep = _walk_forward(close, bench)
        rep.sembol = sym
        rows.append(rep)

    return BacktestReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        config_hash=_config_hash(),
        symbols=rows,
        lookahead_ok=la_ok,
        notes="Skor≥65 walk-forward; buy&hold 1Y karşılaştırma referansı",
    )


def write_report(report: BacktestReport, path: Optional[Path] = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or REPORT_DIR / "signal_backtest_report.json"
    payload = {
        "generated_at": report.generated_at,
        "config_hash": report.config_hash,
        "lookahead_ok": report.lookahead_ok,
        "notes": report.notes,
        "symbols": [asdict(s) for s in report.symbols],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = REPORT_DIR / "signal_backtest_report.md"

    def _fmt(v, suffix="%"):
        return f"{v:.1f}{suffix}" if v is not None else "—"

    lines = [
        "# Signal Backtest Report",
        f"Generated: {report.generated_at}",
        f"Config hash: `{report.config_hash}`",
        f"Lookahead OK: {report.lookahead_ok}",
        "",
        "| Sembol | Sinyal | 1M ort | 3M ort | 6M ort | Hit 1M | B&H 1Y | Sharpe |",
        "|--------|--------|--------|--------|--------|--------|--------|--------|",
    ]
    for s in report.symbols:
        hit = s.hit_rate_1m * 100 if s.hit_rate_1m is not None else None
        lines.append(
            f"| {s.sembol} | {s.signal_count} | {_fmt(s.avg_ret_1m)} | {_fmt(s.avg_ret_3m)} | "
            f"{_fmt(s.avg_ret_6m)} | {_fmt(hit)} | {_fmt(s.buy_hold_1y)} | "
            f"{_fmt(s.sharpe_signal, '')} |"
        )
    md.write_text("\n".join(lines), encoding="utf-8")
    return path


def ci_check(expected_hash: Optional[str] = None) -> bool:
    """Rapor var mı ve config hash uyuyor mu."""
    path = REPORT_DIR / "signal_backtest_report.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    current = _config_hash()
    if data.get("config_hash") != current:
        return False
    if expected_hash and data.get("config_hash") != expected_hash:
        return False
    return bool(data.get("lookahead_ok"))
