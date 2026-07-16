# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_PATH = Path(__file__).resolve().parent / "etf_quality.yaml"
_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def load_etf_quality() -> Dict[str, Dict[str, Any]]:
    global _CACHE
    if _CACHE is None:
        raw = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
        _CACHE = {str(k): dict(v) for k, v in raw.items()}
    return _CACHE


def etf_meta(isin: str) -> Optional[Dict[str, Any]]:
    if not isin:
        return None
    return load_etf_quality().get(isin.strip().upper())
