# -*- coding: utf-8 -*-
"""Karar sentezi A/B backtest — base decide vs synthesize_action.

Price-only MVP: fund_label sabit NÖTR, peer yok, fund_gate yok (indicative değil —
temel snapshot kullanılmıyor). Ichimoku + spot_near + rejim sentez kuralları işler.

Look-ahead: sinyal yalnızca close[:i+1]; ileri getiri değerlendirme için.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from signal_engine.config.loader import load_signal_config
from signal_engine.data.bars import BarSeries
from signal_engine.decisions.decision_synth import synthesize_action
from signal_engine.decisions.state_machine import decide
from signal_engine.entry.ichimoku import compute_ichimoku_zone
from signal_engine.entry.levels import EntrySanityError, compute_entry
from signal_engine.factors.compute import (
    liquidity_factor,
    mean_reversion_factor,
    relative_strength_factor,
    trend_factor,
    volatility_factor,
)
from signal_engine.regime.classifier import classify_regime
from signal_engine.scoring.composite import composite_score

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "CSCO", "AMAT", "KO"]
STEP = 5  # her 5 işlem günü (hız)
MIN_BARS = 300
HORIZONS = (21, 63, 126)  # 1M / 3M / 6M


@dataclass
class ArmStats:
    n: int = 0
    avg_ret_1m: Optional[float] = None
    avg_ret_3m: Optional[float] = None
    avg_ret_6m: Optional[float] = None
    hit_rate_1m: Optional[float] = None


@dataclass
class SymbolAB:
    sembol: str
    bars: int
    base: ArmStats = field(default_factory=ArmStats)
    synth: ArmStats = field(default_factory=ArmStats)
    both_buy: ArmStats = field(default_factory=ArmStats)
    synth_upgrade: ArmStats = field(default_factory=ArmStats)  # base değil, synth AL
    synth_downgrade: ArmStats = field(default_factory=ArmStats)  # base AL, synth değil
    n_agree_buy: int = 0
    n_upgrade: int = 0
    n_downgrade: int = 0
    n_base_buy: int = 0
    n_synth_buy: int = 0


@dataclass
class SynthABReport:
    generated_at: str
    symbols: List[SymbolAB] = field(default_factory=list)
    lookahead_ok: bool = True
    step: int = STEP
    fund_mode: str = "price_only_neutral"
    notes: List[str] = field(default_factory=list)
    aggregate: Dict[str, ArmStats] = field(default_factory=dict)
    confidence_note: str = ""


def _fwd(close: pd.Series, i: int, days: int) -> Optional[float]:
    if i + days >= len(close):
        return None
    a, b = float(close.iloc[i]), float(close.iloc[i + days])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _arm_from_rets(r1: List[float], r3: List[float], r6: List[float]) -> ArmStats:
    def avg(xs):
        return float(np.mean(xs)) if xs else None

    def hit(xs):
        return float(np.mean([1.0 if x > 0 else 0.0 for x in xs])) if xs else None

    return ArmStats(
        n=len(r1),
        avg_ret_1m=avg(r1),
        avg_ret_3m=avg(r3),
        avg_ret_6m=avg(r6),
        hit_rate_1m=hit(r1),
    )


def _is_buy(code: str) -> bool:
    return code in ("BUY", "STRONG_BUY")


def decide_pair_at(
    close: pd.Series,
    bench: pd.Series,
    i: int,
    *,
    fund_label: str = "NÖTR",
) -> Tuple[str, str, dict]:
    """Truncated bar'da (base_code, synth_code, meta)."""
    cfg = load_signal_config()
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
    regime = classify_regime(sb, cfg)
    try:
        entry = compute_entry(sb, regime.regime, cfg)
    except EntrySanityError:
        entry = None

    if entry is None:
        from signal_engine.entry.levels import EntryLevel

        entry = EntryLevel(None, "—", None, False, spot_near=False, spot_distance_pct=None)

    dec = decide(score, 50.0, regime, entry, cfg, prev_code="")
    base = dec.code
    ichi = compute_ichimoku_zone(sb)
    synth = synthesize_action(
        base,
        fund_label=fund_label,
        peer=None,
        spot_near=bool(entry.spot_near),
        spot_distance_pct=entry.spot_distance_pct,
        ichimoku_buy_zone=bool(ichi.buy_zone),
        ichimoku_note=ichi.note or "",
        regime=regime.regime,
        tech_score=float(score),
        gates=list(dec.gates or []),
    )
    meta = {
        "score": score,
        "regime": regime.regime,
        "spot_near": entry.spot_near,
        "ichimoku_buy_zone": ichi.buy_zone,
        "synth_reason": synth.reason,
        "small_size": synth.small_size,
    }
    return base, synth.code, meta


def walk_symbol_ab(
    close: pd.Series,
    bench: pd.Series,
    sembol: str,
    *,
    step: int = STEP,
    fund_label: str = "NÖTR",
) -> SymbolAB:
    out = SymbolAB(sembol=sembol, bars=len(close))
    if len(close) < MIN_BARS:
        return out

    buckets = {
        "base": ([], [], []),
        "synth": ([], [], []),
        "both": ([], [], []),
        "up": ([], [], []),
        "down": ([], [], []),
    }

    last = len(close) - HORIZONS[-1]
    for i in range(252, last, max(1, step)):
        try:
            base, synth, _meta = decide_pair_at(
                close, bench, i, fund_label=fund_label,
            )
        except Exception:
            continue
        b_buy, s_buy = _is_buy(base), _is_buy(synth)
        r1, r3, r6 = _fwd(close, i, 21), _fwd(close, i, 63), _fwd(close, i, 126)
        if r1 is None:
            continue

        def _add(key: str):
            buckets[key][0].append(r1)
            if r3 is not None:
                buckets[key][1].append(r3)
            if r6 is not None:
                buckets[key][2].append(r6)

        if b_buy:
            out.n_base_buy += 1
            _add("base")
        if s_buy:
            out.n_synth_buy += 1
            _add("synth")
        if b_buy and s_buy:
            out.n_agree_buy += 1
            _add("both")
        if s_buy and not b_buy:
            out.n_upgrade += 1
            _add("up")
        if b_buy and not s_buy:
            out.n_downgrade += 1
            _add("down")

    out.base = _arm_from_rets(*buckets["base"])
    out.synth = _arm_from_rets(*buckets["synth"])
    out.both_buy = _arm_from_rets(*buckets["both"])
    out.synth_upgrade = _arm_from_rets(*buckets["up"])
    out.synth_downgrade = _arm_from_rets(*buckets["down"])
    return out


def _merge_arms(rows: List[SymbolAB], attr: str) -> ArmStats:
    r1, r3, r6 = [], [], []
    for row in rows:
        arm: ArmStats = getattr(row, attr)
        # We don't keep raw rets — approximate by weighting isn't possible.
        # Aggregate n and weighted avg if present.
        if arm.n <= 0:
            continue
        if arm.avg_ret_1m is not None:
            r1.extend([arm.avg_ret_1m] * arm.n)  # rough: use mean as proxy weight
        if arm.avg_ret_3m is not None:
            r3.extend([arm.avg_ret_3m] * arm.n)
        if arm.avg_ret_6m is not None:
            r6.extend([arm.avg_ret_6m] * arm.n)
    return _arm_from_rets(r1, r3, r6)


def aggregate_report(rows: List[SymbolAB]) -> Dict[str, ArmStats]:
    return {
        "base": _merge_arms(rows, "base"),
        "synth": _merge_arms(rows, "synth"),
        "both_buy": _merge_arms(rows, "both_buy"),
        "synth_upgrade": _merge_arms(rows, "synth_upgrade"),
        "synth_downgrade": _merge_arms(rows, "synth_downgrade"),
    }


def generate_synth_ab_report(
    closes: Dict[str, pd.Series],
    bench: pd.Series,
    *,
    step: int = STEP,
    fund_label: str = "NÖTR",
    lookahead_ok: bool = True,
) -> SynthABReport:
    rows = [
        walk_symbol_ab(closes[s], bench, s, step=step, fund_label=fund_label)
        for s in closes
    ]
    agg = aggregate_report(rows)
    notes = [
        f"Price-only A/B: fund_label={fund_label} sabit; peer/fund_gate yok.",
        "Base = decide() (cold start, percentile=50). Synth = synthesize_action(+Ichimoku+spot).",
        f"Örneklem adımı: her {step} işlem günü.",
        "Sentez upgrade: base İZLE/BEKLE iken synth AL (bölge+temel≥SAĞLAM gerekir).",
        "Sentez downgrade: base AL iken synth İZLE (uzak giriş vb.).",
        "fund_label=NÖTR iken upgrade beklenmez; SAĞLAM ile bölge teşviki test edilir.",
    ]
    conf = _confidence_blurb(agg, rows)
    return SynthABReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        symbols=rows,
        lookahead_ok=lookahead_ok,
        step=step,
        fund_mode=f"price_only_{fund_label}",
        notes=notes,
        aggregate=agg,
        confidence_note=conf,
    )


def _confidence_blurb(agg: Dict[str, ArmStats], rows: List[SymbolAB]) -> str:
    n_up = sum(r.n_upgrade for r in rows)
    n_down = sum(r.n_downgrade for r in rows)
    n_base = sum(r.n_base_buy for r in rows)
    n_synth = sum(r.n_synth_buy for r in rows)
    base = agg.get("base") or ArmStats()
    synth = agg.get("synth") or ArmStats()
    up = agg.get("synth_upgrade") or ArmStats()

    parts = [
        f"Örneklem: base_AL={n_base}, synth_AL={n_synth}, upgrade={n_up}, downgrade={n_down}.",
    ]
    if n_base < 30 or n_synth < 30:
        parts.append("Örneklem küçük (<30) — güven düşük; sonucu nihai kanıt sayma.")
        return " ".join(parts)

    b1, s1 = base.avg_ret_1m, synth.avg_ret_1m
    if b1 is not None and s1 is not None:
        if s1 >= b1 - 0.5:
            parts.append(
                f"Synth 1M ort ({s1:.1f}%) base'e yakın/üstün ({b1:.1f}%) — "
                "sentez 'felaket değil' kapısından geçti (fiyat-only)."
            )
        else:
            parts.append(
                f"Synth 1M ort ({s1:.1f}%) base'in altında ({b1:.1f}%) — "
                "sentez yükseltmelerini sıkılaştır / incele."
            )
    if up.n >= 10 and up.avg_ret_1m is not None:
        if up.avg_ret_1m > 0:
            parts.append(
                f"Upgrade kolları 1M pozitif ({up.avg_ret_1m:.1f}%, n={up.n}) — "
                "bölge teşviki en azından yıkıcı görünmüyor."
            )
        else:
            parts.append(
                f"Upgrade kolları 1M negatif ({up.avg_ret_1m:.1f}%, n={up.n}) — "
                "geç kalmama yükseltmesi maliyetli olabilir."
            )
    return " ".join(parts)


def write_synth_ab_report(report: SynthABReport, path: Optional[Path] = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or REPORT_DIR / "decision_synth_ab_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def arm_dict(a: ArmStats) -> dict:
        return asdict(a)

    payload = {
        "generated_at": report.generated_at,
        "lookahead_ok": report.lookahead_ok,
        "step": report.step,
        "fund_mode": report.fund_mode,
        "notes": report.notes,
        "confidence_note": report.confidence_note,
        "aggregate": {k: arm_dict(v) for k, v in report.aggregate.items()},
        "symbols": [
            {
                "sembol": s.sembol,
                "bars": s.bars,
                "n_base_buy": s.n_base_buy,
                "n_synth_buy": s.n_synth_buy,
                "n_agree_buy": s.n_agree_buy,
                "n_upgrade": s.n_upgrade,
                "n_downgrade": s.n_downgrade,
                "base": arm_dict(s.base),
                "synth": arm_dict(s.synth),
                "both_buy": arm_dict(s.both_buy),
                "synth_upgrade": arm_dict(s.synth_upgrade),
                "synth_downgrade": arm_dict(s.synth_downgrade),
            }
            for s in report.symbols
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = path.with_suffix(".md")
    if md.name.endswith(".json.md"):
        md = path.parent / (path.stem.replace(".json", "") + ".md")
    if path.suffix == ".json":
        md = path.with_name(path.stem + ".md")

    def fmt(v, s="%"):
        return f"{v:.1f}{s}" if v is not None else "—"

    lines = [
        "# Decision Synth A/B Report",
        "",
        f"Generated: `{report.generated_at}`",
        f"Lookahead OK: **{report.lookahead_ok}**",
        f"Fund mode: `{report.fund_mode}` · step={report.step}",
        "",
        "## Güven notu",
        "",
        report.confidence_note or "—",
        "",
        "## Notlar",
        "",
    ]
    for n in report.notes:
        lines.append(f"- {n}")

    lines.extend([
        "",
        "## Aggregate",
        "",
        "| Kol | n | 1M ort | 3M ort | 6M ort | Hit 1M |",
        "|-----|---|--------|--------|--------|--------|",
    ])
    for name, arm in report.aggregate.items():
        hit = arm.hit_rate_1m * 100 if arm.hit_rate_1m is not None else None
        lines.append(
            f"| {name} | {arm.n} | {fmt(arm.avg_ret_1m)} | {fmt(arm.avg_ret_3m)} | "
            f"{fmt(arm.avg_ret_6m)} | {fmt(hit)} |"
        )

    lines.extend([
        "",
        "## Sembol",
        "",
        "| Sembol | base_AL | synth_AL | upgrade | downgrade | base 1M | synth 1M |",
        "|--------|---------|----------|---------|-----------|---------|----------|",
    ])
    for s in report.symbols:
        lines.append(
            f"| {s.sembol} | {s.n_base_buy} | {s.n_synth_buy} | {s.n_upgrade} | "
            f"{s.n_downgrade} | {fmt(s.base.avg_ret_1m)} | {fmt(s.synth.avg_ret_1m)} |"
        )
    lines.extend([
        "",
        "## Nasıl okunur",
        "",
        "- **base**: eski `decide()` AL/GÜÇLÜ AL sonrası getiri",
        "- **synth**: birleşik `synthesize_action` AL sonrası getiri",
        "- **upgrade**: sentezin yeni açtığı AL’ler (geç kalmama teşviki)",
        "- **downgrade**: sentezin kestiği AL’ler (uzak giriş vb.)",
        "",
        "Bu rapor temel skoru dahil etmez (price-only). "
        "Güven 9/10 için PIT temel + daha büyük örneklem gerekir.",
        "",
    ])
    md.write_text("\n".join(lines), encoding="utf-8")
    return path


def download_closes(
    symbols: List[str],
    *,
    period: str = "5y",
) -> Tuple[Dict[str, pd.Series], pd.Series]:
    import yfinance as yf

    tickers = list(symbols) + ["^GSPC"]
    df = yf.download(
        tickers, period=period, group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )
    closes: Dict[str, pd.Series] = {}
    for sym in symbols:
        c = BarSeries.from_df(df, sym).close
        if len(c) >= MIN_BARS:
            closes[sym] = c
    bench = BarSeries.from_df(df, "^GSPC").close
    return closes, bench
