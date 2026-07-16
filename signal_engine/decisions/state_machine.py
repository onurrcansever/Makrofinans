# -*- coding: utf-8
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from signal_engine.config.loader import SignalConfig
from signal_engine.entry.levels import EntryLevel
from signal_engine.regime.classifier import RegimeResult

# Seviye sırası: 0=AZALT … 4=GÜÇLÜ AL
LEVEL_CODES: List[str] = ["REDUCE", "WAIT", "WATCH", "BUY", "STRONG_BUY"]
LEVEL_LABELS: Dict[str, str] = {
    "REDUCE": "AZALT",
    "WAIT": "BEKLE",
    "WATCH": "İZLE",
    "BUY": "AL",
    "STRONG_BUY": "GÜÇLÜ AL",
}


@dataclass
class DecisionResult:
    label: str
    code: str
    why: str
    gates: List[str]


def _thresholds(cfg: SignalConfig) -> Tuple[float, float, float, float, float]:
    d = cfg.decisions
    return (
        float(d.get("strong_buy", 78)),
        float(d.get("buy", 66)),
        float(d.get("watch", 52)),
        float(d.get("wait", 42)),
        float(d.get("hysteresis_margin", 3.0)),
    )


def threshold_at_level(level: int, strong: float, buy: float, watch: float, wait: float) -> float:
    """Seviye `level` için ham giriş eşiği (o seviyede olmak için min skor)."""
    return {4: strong, 3: buy, 2: watch, 1: wait, 0: 0.0}[level]


def raw_level(score: float, strong: float, buy: float, watch: float, wait: float) -> int:
    if score >= strong:
        return 4
    if score >= buy:
        return 3
    if score >= watch:
        return 2
    if score >= wait:
        return 1
    return 0


def decide_with_hysteresis(
    score: float,
    prev_code: str,
    *,
    strong: float,
    buy: float,
    watch: float,
    wait: float,
    margin: float,
) -> str:
    """
    Simetrik histerezis — yukarı threshold+H, aşağı threshold-H.
    prev_code boşsa cold start (ham eşikler).
    """
    raw = raw_level(score, strong, buy, watch, wait)
    if not prev_code or prev_code not in LEVEL_CODES:
        return LEVEL_CODES[raw]

    prev = LEVEL_CODES.index(prev_code)
    if raw == prev:
        return LEVEL_CODES[prev]

    if raw > prev:
        lvl = prev
        while lvl < raw and score >= threshold_at_level(lvl + 1, strong, buy, watch, wait) + margin:
            lvl += 1
        return LEVEL_CODES[lvl]

    lvl = prev
    while lvl > raw and score < threshold_at_level(lvl, strong, buy, watch, wait) - margin:
        lvl -= 1
    return LEVEL_CODES[lvl]


def effective_thresholds(
    prev_code: str,
    cfg: SignalConfig,
) -> Dict[str, float]:
    """
    Mevcut state'e göre etkin eşikler (debug paneli).
    upgrade_to_*: bir üst seviyeye çıkmak için gereken min skor
    hold_at_*: mevcut seviyede kalmak için min skor (düşüş tamponu)
    """
    strong, buy, watch, wait, margin = _thresholds(cfg)
    code = prev_code if prev_code in LEVEL_CODES else ""
    if not code:
        return {
            "strong_buy_enter": strong,
            "buy_enter": buy,
            "watch_enter": watch,
            "wait_enter": wait,
        }
    lvl = LEVEL_CODES.index(code)
    out: Dict[str, float] = {}
    if lvl < 4:
        out["upgrade_to_strong_buy"] = strong + margin
    if lvl < 3:
        out["upgrade_to_buy"] = buy + margin
    if lvl < 2:
        out["upgrade_to_watch"] = watch + margin
    if lvl < 1:
        out["upgrade_to_wait"] = wait + margin
    if lvl >= 1:
        out[f"hold_at_{LEVEL_LABELS[code].lower()}"] = threshold_at_level(lvl, strong, buy, watch, wait) - margin
    return out


def format_effective_threshold_lines(code: str, cfg: SignalConfig) -> list[str]:
    """Mevcut karar seviyesine göre etkin eşik satırları (debug / Neden? paneli)."""
    strong, buy, watch, wait, margin = _thresholds(cfg)
    h = margin
    lines = [f"- Histerezis: {h:.0f} puan (simetrik)"]
    if not code or code not in LEVEL_CODES:
        lines.insert(0, f"- GÜÇLÜ AL ≥ {strong:.0f}")
        lines.insert(1, f"- AL ≥ {buy:.0f}")
        lines.insert(2, f"- İZLE ≥ {watch:.0f}")
        lines.insert(3, f"- BEKLE ≥ {wait:.0f}")
        return lines
    lvl = LEVEL_CODES.index(code)
    label = LEVEL_LABELS[code]
    hold = threshold_at_level(lvl, strong, buy, watch, wait) - h
    lines.insert(0, f"- {label}'de kalma ≥ {hold:.0f} (düşüş tamponu)")
    if lvl < 4:
        nxt = LEVEL_CODES[lvl + 1]
        thr = threshold_at_level(lvl + 1, strong, buy, watch, wait) + h
        lines.insert(0, f"- {LEVEL_LABELS[nxt]}'a geçiş ≥ {thr:.0f}")
    return lines


def distance_to_next_upgrade(score: float, prev_code: str, cfg: SignalConfig) -> Optional[Tuple[str, float]]:
    """Bir üst seviyeye etkin mesafe (puan). Negatif = henüz yeterli değil."""
    strong, buy, watch, wait, margin = _thresholds(cfg)
    if not prev_code or prev_code not in LEVEL_CODES:
        code = LEVEL_CODES[raw_level(score, strong, buy, watch, wait)]
    else:
        code = prev_code
    lvl = LEVEL_CODES.index(code)
    if lvl >= 4:
        return None
    next_lvl = lvl + 1
    thr = threshold_at_level(next_lvl, strong, buy, watch, wait) + margin
    return LEVEL_LABELS[LEVEL_CODES[next_lvl]], score - thr


def distance_to_next_downgrade(score: float, code: str, cfg: SignalConfig) -> Optional[Tuple[str, float]]:
    """Bir alt seviyeye düşüş tamponu mesafesi. Pozitif = henüz düşmez (≥ hold)."""
    strong, buy, watch, wait, margin = _thresholds(cfg)
    if not code or code not in LEVEL_CODES:
        return None
    lvl = LEVEL_CODES.index(code)
    if lvl <= 0:
        return None
    hold = threshold_at_level(lvl, strong, buy, watch, wait) - margin
    lower = LEVEL_CODES[lvl - 1]
    return LEVEL_LABELS[lower], score - hold


def hysteresis_panel_note(
    score: float,
    code: str,
    prev_code: str,
    *,
    cold_start: bool,
    cold_reason: str,
    cfg: SignalConfig,
) -> str:
    """Panel şeffaflığı — skor vs karar uyumsuzluğunu açıkla."""
    if cold_start and cold_reason:
        return cold_reason
    if not code or code not in LEVEL_CODES:
        return ""
    strong, buy, watch, wait, margin = _thresholds(cfg)
    raw = raw_level(score, strong, buy, watch, wait)
    raw_code = LEVEL_CODES[raw]
    if code == raw_code:
        return ""
    lvl = LEVEL_CODES.index(code)
    if lvl > raw and prev_code:
        hold = threshold_at_level(lvl, strong, buy, watch, wait) - margin
        label = LEVEL_LABELS[code]
        prev_label = LEVEL_LABELS.get(prev_code, prev_code)
        return (
            f"{label}'da tutuluyor (histerez): önceki karar {prev_label}, "
            f"çıkış için skor < {hold:.0f} gerekir."
        )
    return ""


def decide(
    score: float,
    percentile: float,
    regime: RegimeResult,
    entry: EntryLevel,
    cfg: SignalConfig,
    prev_code: str = "",
) -> DecisionResult:
    strong, buy, watch, wait, margin = _thresholds(cfg)
    raw_code = LEVEL_CODES[raw_level(score, strong, buy, watch, wait)]
    code = decide_with_hysteresis(
        score, prev_code,
        strong=strong, buy=buy, watch=watch, wait=wait, margin=margin,
    )
    gates: List[str] = []
    if prev_code and prev_code != code and prev_code != raw_code:
        gates.append(f"Histerezis: ham {LEVEL_LABELS.get(raw_code, raw_code)} → {LEVEL_LABELS[code]}")

    if regime.regime == "TRENDING_DOWN" and code == "STRONG_BUY":
        gates.append("Rejim TRENDING_DOWN: GÜÇLÜ AL → İZLE")
        code = "WATCH"

    label = LEVEL_LABELS[code]
    why = format_decision_why(
        score, percentile, regime.regime,
        entry_method=getattr(entry, "method", "") or "",
        prev_code=prev_code, code=code, gates=gates,
    )
    return DecisionResult(label=label, code=code, why=why, gates=gates)


def format_decision_why(
    score: float,
    percentile: float,
    regime: str,
    *,
    entry_method: str = "",
    prev_code: str = "",
    code: str = "",
    gates: Optional[List[str]] = None,
) -> str:
    """İtalik özet — her zaman güncel percentile ile (sabit %50 değil)."""
    why_parts = [
        f"Skor {float(score):.0f} (sınıf %{float(percentile):.0f})",
        f"Rejim {regime}" if regime else "",
        f"Giriş {entry_method}" if entry_method and entry_method != "—" else "",
    ]
    gates = gates or []
    if prev_code and code and prev_code != code and not any("Histerezis" in g for g in gates):
        why_parts.append(f"Histerez {prev_code}→{code}")
    return " · ".join(x for x in why_parts if x)
