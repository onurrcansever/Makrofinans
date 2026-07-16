# -*- coding: utf-8
"""Signal engine anti-degeneracy ve debug raporları."""
from __future__ import annotations

import math
from collections import Counter
from typing import List, Optional

import numpy as np


def label_entropy(labels: List[str]) -> float:
    if not labels:
        return 0.0
    counts = Counter(labels)
    n = len(labels)
    ent = 0.0
    for c in counts.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def assert_label_distribution(labels: List[str], *, min_entropy: float = 0.8) -> None:
    """Tek sınıf çöküşünü yakalar."""
    if len(labels) < 5:
        return
    ent = label_entropy(labels)
    dominant = max(Counter(labels).values()) / len(labels)
    if dominant > 0.70:
        raise AssertionError(f"Label collapse: {dominant*100:.0f}% tek sınıf, entropy={ent:.2f}")
    if ent < min_entropy:
        raise AssertionError(f"Label entropy too low: {ent:.2f} < {min_entropy}")


def assert_p_fill_distribution(p_fills: List[float], *, min_std_pp: float = 10.0) -> None:
    """P(fill) dağılımı sabit 100% olmamalı."""
    vals = [round(v * 100) for v in p_fills if v is not None]
    if len(vals) < 5:
        return
    std = float(np.std(vals))
    if std <= min_std_pp:
        raise AssertionError(f"P(fill) degenerate: std={std:.1f}pp (need >{min_std_pp})")
    top_share = max(Counter(vals).values()) / len(vals)
    if top_share > 0.50:
        raise AssertionError(f"P(fill) >50% rows share same rounded value ({top_share*100:.0f}%)")


def debug_threshold_report(h) -> str:
    """Etkin histerez mesafeleri — ham eşik değil."""
    from signal_engine.config.loader import load_signal_config
    from signal_engine.decisions.state_machine import (
        LEVEL_LABELS,
        distance_to_next_downgrade,
        distance_to_next_upgrade,
        format_effective_threshold_lines,
    )

    cfg = load_signal_config()
    score = getattr(h, "signal_v2_score", None) or 0
    code = getattr(h, "signal_v2_code", "") or ""
    decision = getattr(h, "signal_v2_decision", "—")

    lines = [f"**{h.sembol}** skor={score:.0f} → {decision}"]
    note = getattr(h, "signal_v2_hysteresis_note", "") or ""
    if note:
        lines.append(f"  ℹ {note}")
    cold_reason = getattr(h, "signal_v2_cold_reason", "") or ""
    if getattr(h, "signal_v2_cold_start", False) and cold_reason and not note:
        lines.append(f"  ⚠ {cold_reason}")

    up = distance_to_next_upgrade(score, code, cfg)
    if up:
        label, dist = up
        lines.append(f"  ↑ {label}: {dist:+.0f} puan")
    down = distance_to_next_downgrade(score, code, cfg)
    if down:
        label, dist = down
        lines.append(f"  ↓ {label}: {dist:+.0f} puan")

    lines.append("  Etkin eşikler:")
    for ln in format_effective_threshold_lines(code, cfg):
        lines.append(f"    {ln}")

    factors = getattr(h, "signal_v2_factors", {}) or {}
    if factors:
        lines.append("  Faktörler: " + ", ".join(f"{k}={v:.0f}" for k, v in factors.items()))
    gates = getattr(h, "signal_v2_decision_gates", None) or []
    if gates:
        lines.append("  Karar katmanları:")
        for g in gates:
            lines.append(f"    · {g}")
    return "\n".join(lines)
