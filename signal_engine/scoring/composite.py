# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from signal_engine.config.loader import SignalConfig
from signal_engine.factors.compute import FactorResult


@dataclass
class CompositeResult:
    score: float
    percentile: float
    factors_used: int
    factors_total: int
    factor_scores: Dict[str, float] = field(default_factory=dict)
    factor_details: Dict[str, str] = field(default_factory=dict)


def composite_score(
    factors: Dict[str, FactorResult],
    cfg: SignalConfig,
) -> Tuple[float, int, int]:
    weights = cfg.weights
    total_w = 0.0
    acc = 0.0
    used = 0
    for name, w in weights.items():
        fr = factors.get(name)
        if fr and fr.available:
            acc += fr.score * w
            total_w += w
            used += 1
    if total_w <= 0:
        return 50.0, 0, len(weights)
    return max(0.0, min(100.0, acc / total_w)), used, len(weights)


def percentile_within_class(scores: List[float], value: float) -> float:
    if not scores:
        return 50.0
    below = sum(1 for s in scores if s < value)
    equal = sum(1 for s in scores if s == value)
    return round((below + 0.5 * equal) / len(scores) * 100, 1)


def rank_composites(
    items: List[Tuple[object, CompositeResult]],
) -> None:
    """Aynı asset_class içinde percentile yazar."""
    by_class: Dict[str, List] = {}
    for h, comp in items:
        ac = getattr(h, "_signal_asset_class", "global_stock")
        by_class.setdefault(ac, []).append(comp)
    for ac, comps in by_class.items():
        vals = [c.score for c in comps]
        for c in comps:
            c.percentile = percentile_within_class(vals, c.score)
