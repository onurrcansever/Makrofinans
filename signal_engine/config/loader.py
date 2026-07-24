# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "signal_config.yaml"


@dataclass
class SignalConfig:
    version: int = 2
    history: Dict[str, Any] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    regime: Dict[str, float] = field(default_factory=dict)
    entry: Dict[str, Any] = field(default_factory=dict)
    decisions: Dict[str, float] = field(default_factory=dict)
    benchmarks: Dict[str, str] = field(default_factory=dict)
    asset_classes: Dict[str, List[str]] = field(default_factory=dict)
    short_momentum: Dict[str, Any] = field(default_factory=dict)


def load_signal_config(path: Path | None = None) -> SignalConfig:
    p = path or _CONFIG_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return SignalConfig(
        version=int(raw.get("version", 2)),
        history=dict(raw.get("history") or {}),
        weights={k: float(v) for k, v in (raw.get("weights") or {}).items()},
        regime={k: float(v) for k, v in (raw.get("regime") or {}).items()},
        entry=dict(raw.get("entry") or {}),
        decisions={k: float(v) for k, v in (raw.get("decisions") or {}).items()},
        benchmarks=dict(raw.get("benchmarks") or {}),
        asset_classes=dict(raw.get("asset_classes") or {}),
        short_momentum=dict(raw.get("short_momentum") or {}),
    )
