# -*- coding: utf-8 -*-
"""Runtime dosya yolları — import anında os.getenv bağlamayı önler."""
from __future__ import annotations

import os


def market_cache_db() -> str:
    return os.getenv("MARKET_CACHE_DB", "market_cache.db")
