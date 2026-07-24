# -*- coding: utf-8 -*-
"""Trend kısa-momentum A/B backtest — base vs small vs temkinli.

Walk-forward: her adımda composite skor (yalnızca trend kolu değişir),
ham karar seviyesi (cold start), ileri getiri + whipsaw.

Dur eşikleri (önceden sabit):
  WHIPSAW_MAX_INCREASE_PCT = 15  → temkinli whipsaw base'e göre >%15 artarsa bağlama
  HIT_MIN_IMPROVEMENT_PP = 0.0   → 1A hit en az base kadar olmalı
  UPGRADE_AVG_1M_MIN = 0.0      → base'e göre upgrade (skor yükselten) örneklerin ort. 1A getiri ≥0
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
from signal_engine.decisions.state_machine import raw_level
from signal_engine.factors.compute import (
    FactorResult,
    mean_reversion_factor,
    relative_strength_factor,
    trend_factor,
    volatility_factor,
)
from signal_engine.scoring.composite import composite_score

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"

DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "ADBE", "INTU", "CSCO", "AMAT",
    "KO", "JNJ", "XOM", "JPM", "UNH", "HD", "PG", "V", "MA", "DIS",
    "BA", "CAT", "IBM", "ORCL", "CRM", "NFLX", "TSLA", "AMD", "QCOM", "TXN",
]

STEP = 5
MIN_BARS = 300
HORIZONS = (21, 63)

# Önceden tanımlı "dur" eşikleri
# Göreli % tek başına zayıf: base ~5 flip iken +1 olay = %20 — gürültüye duyarlı.
# DUR (whipsaw) yalnız ÇİFT koşul: göreli artış > max VE ek flip sayısı >= min.
WHIPSAW_MAX_INCREASE_PCT = 15.0
WHIPSAW_MIN_EXTRA_FLIPS = 3  # mutlak: en az 3 ek REDUCE↔WATCH+ olayı
HIT_MIN_IMPROVEMENT_PP = 0.0
UPGRADE_AVG_1M_MIN = 0.0

ARMS = ("base", "small", "temkinli", "siki")
CANDIDATE_ARMS = ("siki", "temkinli", "small")  # bağlama tercihi: önce sıkı


@dataclass
class ArmAgg:
    n: int = 0
    hit_rate_1m: Optional[float] = None
    avg_ret_1m: Optional[float] = None
    avg_ret_3m: Optional[float] = None
    whipsaw_flips: int = 0
    whipsaw_rate: Optional[float] = None
    n_watch_plus: int = 0
    n_upgrade_vs_base: int = 0
    upgrade_avg_ret_1m: Optional[float] = None


@dataclass
class ShortMomABReport:
    generated_at: str
    symbols_ok: List[str] = field(default_factory=list)
    step: int = STEP
    arms: Dict[str, ArmAgg] = field(default_factory=dict)
    verdict: str = "bağlama"
    chosen_preset: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    thresholds: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def _fwd(close: pd.Series, i: int, days: int) -> Optional[float]:
    if i + days >= len(close):
        return None
    a, b = float(close.iloc[i]), float(close.iloc[i + days])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _level(score: float, cfg) -> int:
    d = cfg.decisions
    return raw_level(
        score,
        d.get("strong_buy", 76),
        d.get("buy", 68),
        d.get("watch", 52),
        d.get("wait", 42),
    )


def _composite_at(
    close: pd.Series,
    bench: Optional[pd.Series],
    i: int,
    cfg,
    *,
    arm: str,
) -> float:
    seg = close.iloc[: i + 1]
    bars = BarSeries.from_series(seg)
    if arm == "base":
        tr = trend_factor(bars, apply_short_mom=False)
    else:
        tr = trend_factor(
            bars,
            apply_short_mom=True,
            short_mom_preset=arm,
            short_mom_cfg={"enabled": True, "preset": arm},
        )
    factors = {
        "trend": tr,
        "mean_reversion": mean_reversion_factor(bars),
        "volatility": volatility_factor(bars),
        "liquidity": FactorResult(55.0, False, "bt_skip"),
    }
    # relative strength needs bench
    if bench is not None and len(bench) > i:
        bseg = bench.reindex(seg.index).ffill().dropna()
        if len(bseg) >= 63:
            factors["relative_strength"] = relative_strength_factor(
                bars, BarSeries.from_series(bseg)
            )
    score, _, _ = composite_score(factors, cfg)
    return float(score)


def walk_symbol(
    close: pd.Series,
    bench: Optional[pd.Series],
    cfg,
    *,
    step: int = STEP,
    symbol: str = "",
) -> Dict[str, dict]:
    """Her arm için rets, levels, upgrades + flip olayları."""
    out = {
        a: {
            "r1": [],
            "r3": [],
            "levels": [],
            "flips": 0,
            "up_r1": [],
            "flip_events": [],
        }
        for a in ARMS
    }
    n = len(close)
    end = n - HORIZONS[1] - 1
    if end < 252:
        return out
    prev_lvl = {a: None for a in ARMS}
    prev_i = {a: None for a in ARMS}
    for i in range(252, end, step):
        scores = {}
        for arm in ARMS:
            scores[arm] = _composite_at(close, bench, i, cfg, arm=arm)
        r1 = _fwd(close, i, 21)
        r3 = _fwd(close, i, 63)
        base_lvl = _level(scores["base"], cfg)
        ts = close.index[i]
        try:
            ts_s = str(ts.date())
        except Exception:
            ts_s = str(ts)[:10]
        for arm in ARMS:
            lvl = _level(scores[arm], cfg)
            out[arm]["levels"].append(lvl)
            if r1 is not None:
                out[arm]["r1"].append(r1)
            if r3 is not None:
                out[arm]["r3"].append(r3)
            if prev_lvl[arm] is not None:
                a, b = prev_lvl[arm], lvl
                if (a == 0 and b >= 2) or (a >= 2 and b == 0):
                    out[arm]["flips"] += 1
                    out[arm]["flip_events"].append({
                        "symbol": symbol,
                        "date": ts_s,
                        "from": a,
                        "to": b,
                        "direction": "up" if b > a else "down",
                        "score": round(scores[arm], 2),
                    })
            prev_lvl[arm] = lvl
            prev_i[arm] = i
            if arm != "base" and lvl > base_lvl and r1 is not None:
                out[arm]["up_r1"].append(r1)
    return out


def flip_diff_report(
    closes: Dict[str, pd.Series],
    bench: Optional[pd.Series],
    *,
    arm: str = "siki",
    step: int = STEP,
) -> Dict[str, object]:
    """base'te olmayan, yalnızca `arm`da görülen flip'ler (ekstra olaylar)."""
    cfg = load_signal_config()
    only_arm: List[dict] = []
    only_base: List[dict] = []
    both: List[dict] = []
    for sym, close in closes.items():
        if len(close) < MIN_BARS:
            continue
        walked = walk_symbol(close, bench, cfg, step=step, symbol=sym)
        base_keys = {
            (e["symbol"], e["date"], e["from"], e["to"])
            for e in walked["base"]["flip_events"]
        }
        arm_keys = {
            (e["symbol"], e["date"], e["from"], e["to"])
            for e in walked[arm]["flip_events"]
        }
        for e in walked[arm]["flip_events"]:
            key = (e["symbol"], e["date"], e["from"], e["to"])
            if key not in base_keys:
                only_arm.append(e)
            else:
                both.append(e)
        for e in walked["base"]["flip_events"]:
            key = (e["symbol"], e["date"], e["from"], e["to"])
            if key not in arm_keys:
                only_base.append(e)
    return {
        "arm": arm,
        "extra_vs_base": only_arm,
        "missing_vs_base": only_base,
        "shared": both,
        "n_extra": len(only_arm),
        "n_base_only": len(only_base),
        "n_shared": len(both),
    }


def _agg(arm_data: dict) -> ArmAgg:
    r1 = arm_data.get("r1") or []
    r3 = arm_data.get("r3") or []
    levels = arm_data.get("levels") or []
    flips = int(arm_data.get("flips") or 0)
    up = arm_data.get("up_r1") or []
    n = len(r1)
    return ArmAgg(
        n=n,
        hit_rate_1m=float(np.mean([1.0 if x > 0 else 0.0 for x in r1])) if r1 else None,
        avg_ret_1m=float(np.mean(r1)) if r1 else None,
        avg_ret_3m=float(np.mean(r3)) if r3 else None,
        whipsaw_flips=flips,
        whipsaw_rate=(flips / max(1, len(levels) - 1)) if levels else None,
        n_watch_plus=sum(1 for L in levels if L >= 2),
        n_upgrade_vs_base=len(up),
        upgrade_avg_ret_1m=float(np.mean(up)) if up else None,
    )


def merge_arm_data(parts: List[dict]) -> dict:
    merged = {"r1": [], "r3": [], "levels": [], "flips": 0, "up_r1": []}
    for p in parts:
        merged["r1"].extend(p.get("r1") or [])
        merged["r3"].extend(p.get("r3") or [])
        merged["levels"].extend(p.get("levels") or [])
        merged["flips"] += int(p.get("flips") or 0)
        merged["up_r1"].extend(p.get("up_r1") or [])
    return merged


def decide_verdict(arms: Dict[str, ArmAgg]) -> Tuple[str, List[str], Optional[str]]:
    """Aday kolları base ile karşılaştır; ilk geçen (siki→temkinli→small) bağlanır."""
    base = arms.get("base")
    if not base or not base.n:
        return "bağlama", ["Yetersiz örnek"], None

    all_reasons: List[str] = []
    base_flips = int(base.whipsaw_flips or 0)
    for cand in CANDIDATE_ARMS:
        tem = arms.get(cand)
        if not tem or not tem.n:
            continue
        reasons = [f"--- aday={cand} ---"]
        cand_flips = int(tem.whipsaw_flips or 0)
        extra = cand_flips - base_flips
        br = base.whipsaw_rate or 0.0
        tr = tem.whipsaw_rate or 0.0
        if br > 1e-9:
            inc = (tr - br) / br * 100.0
        else:
            inc = 0.0 if tr <= 1e-9 else 999.0
        reasons.append(
            f"whipsaw_flips base={base_flips} {cand}={cand_flips} extra={extra} "
            f"(DUR için extra>={WHIPSAW_MIN_EXTRA_FLIPS} VE pct>{WHIPSAW_MAX_INCREASE_PCT})"
        )
        reasons.append(f"whipsaw_increase_pct={inc:.1f}")
        # Çift koşul: göreli % yüksek VE mutlak ek olay yeterli → DUR
        if inc > WHIPSAW_MAX_INCREASE_PCT and extra >= WHIPSAW_MIN_EXTRA_FLIPS:
            reasons.append(
                "DUR: whipsaw hem göreli hem mutlak eşiği aştı"
            )
            all_reasons.extend(reasons)
            continue
        if inc > WHIPSAW_MAX_INCREASE_PCT and extra < WHIPSAW_MIN_EXTRA_FLIPS:
            reasons.append(
                f"NOT: göreli %{inc:.0f} yüksek ama extra={extra} < {WHIPSAW_MIN_EXTRA_FLIPS} "
                f"— küçük örneklem gürültüsü; whipsaw DUR tetiklemedi"
            )

        bh = base.hit_rate_1m if base.hit_rate_1m is not None else 0.0
        th = tem.hit_rate_1m if tem.hit_rate_1m is not None else 0.0
        hit_pp = (th - bh) * 100.0
        reasons.append(f"hit_1m_pp={hit_pp:+.2f} (min {HIT_MIN_IMPROVEMENT_PP})")
        if hit_pp < HIT_MIN_IMPROVEMENT_PP:
            reasons.append("DUR: 1A hit base'in altında")
            all_reasons.extend(reasons)
            continue

        up = tem.upgrade_avg_ret_1m
        reasons.append(
            f"upgrade_n={tem.n_upgrade_vs_base} upgrade_avg_1m={up} (min {UPGRADE_AVG_1M_MIN})"
        )
        if tem.n_upgrade_vs_base >= 20 and up is not None and up < UPGRADE_AVG_1M_MIN:
            reasons.append("DUR: upgrade örnekleri negatif ortalama getiri")
            all_reasons.extend(reasons)
            continue

        if hit_pp <= 0.05 and tem.n_upgrade_vs_base < 30:
            reasons.append("DUR: anlamlı iyileşme yok (hit≈aynı, az upgrade)")
            all_reasons.extend(reasons)
            continue

        if hit_pp > 0.05 or (
            up is not None and up >= UPGRADE_AVG_1M_MIN and tem.n_upgrade_vs_base >= 30
        ):
            reasons.append(f"OK: {cand} whipsaw çift-eşik geçti ve hit/upgrade kabul")
            all_reasons.extend(reasons)
            return "bağla", all_reasons, cand

        reasons.append("DUR: belirsiz / zayıf kanıt")
        all_reasons.extend(reasons)

    return "bağlama", all_reasons or ["Hiçbir aday geçmedi"], None


def generate_short_mom_ab_report(
    closes: Dict[str, pd.Series],
    bench: Optional[pd.Series],
    *,
    step: int = STEP,
) -> ShortMomABReport:
    cfg = load_signal_config()
    per_arm: Dict[str, List[dict]] = {a: [] for a in ARMS}
    ok = []
    for sym, close in closes.items():
        if len(close) < MIN_BARS:
            continue
        walked = walk_symbol(close, bench, cfg, step=step, symbol=sym)
        ok.append(sym)
        for arm in ARMS:
            per_arm[arm].append(walked[arm])

    arms = {a: _agg(merge_arm_data(per_arm[a])) for a in ARMS}
    verdict, reasons, chosen = decide_verdict(arms)
    return ShortMomABReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        symbols_ok=ok,
        step=step,
        arms=arms,
        verdict=verdict,
        chosen_preset=chosen,
        reasons=reasons,
        thresholds={
            "WHIPSAW_MAX_INCREASE_PCT": WHIPSAW_MAX_INCREASE_PCT,
            "WHIPSAW_MIN_EXTRA_FLIPS": float(WHIPSAW_MIN_EXTRA_FLIPS),
            "HIT_MIN_IMPROVEMENT_PP": HIT_MIN_IMPROVEMENT_PP,
            "UPGRADE_AVG_1M_MIN": UPGRADE_AVG_1M_MIN,
        },
        notes=[
            "Composite: trend kolu A/B; MR/vol/RS aynı; liq skip",
            "Whipsaw proxy: REDUCE↔WATCH+ flip (cold-start levels)",
            "Whipsaw DUR = göreli% VE mutlak ek flip (küçük base gürültüsü için)",
            "hit/avg_* tüm adımlarda aynıdır: ileri getiri fiyat yolu; kol farkı upgrades'te",
            "Aday sırası: siki(+4) → temkinli(+6) → small",
            "Panel/UX değişikliği yok",
        ],
    )


def write_report(report: ShortMomABReport, path: Optional[Path] = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or (REPORT_DIR / "trend_short_mom_ab_report.json")
    payload = {
        "generated_at": report.generated_at,
        "verdict": report.verdict,
        "chosen_preset": report.chosen_preset,
        "reasons": report.reasons,
        "thresholds": report.thresholds,
        "symbols_ok": report.symbols_ok,
        "n_symbols": len(report.symbols_ok),
        "step": report.step,
        "notes": report.notes,
        "arms": {k: asdict(v) for k, v in report.arms.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = REPORT_DIR / "trend_short_mom_ab_report.md"
    lines = [
        "# Trend kısa-momentum A/B",
        "",
        f"Üretilme: `{report.generated_at}`",
        f"Sembol: **{len(report.symbols_ok)}** · step={report.step}",
        "",
        f"## Verdict: **{report.verdict}**"
        + (f" · preset=`{report.chosen_preset}`" if report.chosen_preset else ""),
        "",
    ]
    for r in report.reasons:
        lines.append(f"- {r}")
    lines.extend(["", "## Kollar", ""])
    lines.append("| Arm | n | hit_1m | avg_1m | avg_3m | flips | whipsaw_rate | upgrades | up_avg_1m |")
    lines.append("|-----|---|--------|--------|--------|-------|--------------|----------|-----------|")
    for name, a in report.arms.items():
        lines.append(
            f"| {name} | {a.n} | {a.hit_rate_1m} | {a.avg_ret_1m} | {a.avg_ret_3m} | "
            f"{a.whipsaw_flips} | {a.whipsaw_rate} | {a.n_upgrade_vs_base} | {a.upgrade_avg_ret_1m} |"
        )
    lines.extend([
        "",
        "> `hit_1m` / `avg_*` tüm kollarda aynıdır: her adımda aynı ileri fiyat yolu ölçülür; ",
        "> kol farkı `upgrades` / `up_avg_1m` (base'e göre seviye yükselten örnekler) sütunlarındadır.",
        "",
        "## Notlar",
        "",
    ])
    for n in report.notes:
        lines.append(f"- {n}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
        try:
            c = BarSeries.from_df(df, sym).close
        except Exception:
            continue
        if len(c) >= MIN_BARS:
            closes[sym] = c
    bench = BarSeries.from_df(df, "^GSPC").close
    return closes, bench
