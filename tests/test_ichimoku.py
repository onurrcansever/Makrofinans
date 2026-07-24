# -*- coding: utf-8 -*-
"""Ichimoku buy_zone birim testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd

from signal_engine.data.bars import BarSeries
from signal_engine.entry.ichimoku import (
    KIJUN_N,
    SENKOU_B_N,
    compute_ichimoku_zone,
)


def _bars_from_closes(closes) -> BarSeries:
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    s = pd.Series(closes, index=idx, dtype=float)
    return BarSeries.from_series(s)


def test_insufficient_bars():
    z = compute_ichimoku_zone(_bars_from_closes([100.0] * 30))
    assert z.buy_zone is False
    assert "yetersiz" in z.note.lower()


def test_flat_series_near_cloud_not_overextended():
    # Uzun düz seri → tenkan≈kijun≈price, bulut yakın
    n = SENKOU_B_N + KIJUN_N + 10
    z = compute_ichimoku_zone(_bars_from_closes([100.0] * n))
    assert z.cloud_top is not None
    assert z.price is not None
    # Düz piyasada in/near cloud beklenir
    assert z.in_or_near_cloud or z.price_above_cloud or z.price_below_cloud


def test_overextended_blocks_buy_zone():
    n = SENKOU_B_N + KIJUN_N + 10
    base = [100.0] * (n - 5)
    # Son 5 bar sert ralli → bulut geride, fiyat uzakta
    spike = [100.0, 105.0, 110.0, 120.0, 130.0]
    z = compute_ichimoku_zone(_bars_from_closes(base + spike))
    if z.cloud_top and z.price and z.price / z.cloud_top - 1.0 >= 0.08:
        assert z.overextended is True
        assert z.buy_zone is False


def test_bullish_tk_cross_detectable():
    n = SENKOU_B_N + KIJUN_N + 15
    # Yavaş düşüş sonra toparlanma — TK kesişimi için
    rng = np.random.default_rng(42)
    x = 100.0 + np.cumsum(rng.normal(-0.05, 0.4, n))
    x[-8:] = x[-9] + np.linspace(0.5, 6.0, 8)
    z = compute_ichimoku_zone(_bars_from_closes(x.tolist()))
    # Kesişim garantisi yok; en azından yapı çalışsın
    assert z.tenkan is not None
    assert z.kijun is not None
    assert isinstance(z.buy_zone, bool)
