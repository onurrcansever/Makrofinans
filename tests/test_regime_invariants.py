# -*- coding: utf-8
"""Rejim × karar tutarlılık testleri."""
import unittest

from signal_engine.entry.levels import compute_entry
from signal_engine.config.loader import load_signal_config
from signal_engine.data.bars import BarSeries
from signal_engine.regime.classifier import classify_regime
from signal_engine.decisions.state_machine import decide
import numpy as np
import pandas as pd


def _trend(n=300, start=100.0, drift=0.0008):
    rng = np.random.default_rng(42)
    prices = start * np.cumprod(1 + rng.normal(drift, 0.008, n))
    return pd.Series(prices)


class RegimeInvariantTest(unittest.TestCase):
    def test_trending_up_no_deep_primary(self):
        bars = BarSeries.from_series(_trend())
        cfg = load_signal_config()
        regime = classify_regime(bars, cfg)
        if regime.regime != "TRENDING_UP":
            self.skipTest("not trending up fixture")
        entry = compute_entry(bars, regime.regime, cfg)
        price = float(bars.close.iloc[-1])
        self.assertIsNotNone(entry.price)
        self.assertGreater(entry.price, price * 0.85, "primary >15% below spot in TRENDING_UP")

    def test_trending_down_no_strong_buy(self):
        close = _trend()
        close = close * np.linspace(1.2, 0.7, len(close))
        bars = BarSeries.from_series(close)
        cfg = load_signal_config()
        regime = classify_regime(bars, cfg)
        entry = compute_entry(bars, regime.regime, cfg)
        decision = decide(85.0, 90.0, regime, entry, cfg)
        if regime.regime == "TRENDING_DOWN":
            self.assertNotEqual(decision.code, "STRONG_BUY")


if __name__ == "__main__":
    unittest.main()
