# -*- coding: utf-8
"""P(fill) and label anti-degeneracy tests."""
import unittest

import numpy as np
import pandas as pd

from signal_engine.config.loader import load_signal_config
from signal_engine.data.bars import BarSeries
from signal_engine.decisions.state_machine import decide
from signal_engine.entry.levels import compute_entry, historical_p_fill
from signal_engine.quality.degeneracy import assert_label_distribution
from signal_engine.regime.classifier import classify_regime


def _mixed(n=300, seed=1, vol=0.012, drift=0.0005):
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(drift, vol, n)))


class DegeneracyTest(unittest.TestCase):
    def test_entry_does_not_drive_dca_from_p_fill(self):
        """Bozuk historical_p_fill DCA/karar üretmez."""
        cfg = load_signal_config()
        for i in range(12):
            bars = BarSeries.from_series(_mixed(seed=i, vol=0.008 + i * 0.001))
            reg = classify_regime(bars, cfg)
            ent = compute_entry(bars, reg.regime, cfg)
            self.assertFalse(ent.dca_preferred)
            self.assertIsNone(ent.p_fill_90d)

    def test_historical_p_fill_spot_not_100(self):
        """Dokümantasyon: target==son kapanış → %100 değil (model limit fill değil)."""
        close = _mixed(n=400, seed=7)
        spot = float(close.iloc[-1])
        p = historical_p_fill(close, spot, 90)
        self.assertIsNotNone(p)
        self.assertLess(p, 1.0)

    def test_labels_not_single_class_synthetic(self):
        cfg = load_signal_config()
        labels = []
        for seed in range(20):
            bars = BarSeries.from_series(_mixed(seed=seed + 10))
            reg = classify_regime(bars, cfg)
            ent = compute_entry(bars, reg.regime, cfg)
            from signal_engine.scoring.composite import composite_score
            from signal_engine.factors.compute import (
                trend_factor, mean_reversion_factor, volatility_factor,
                relative_strength_factor, liquidity_factor,
            )
            factors = {
                "trend": trend_factor(bars),
                "mean_reversion": mean_reversion_factor(bars),
                "volatility": volatility_factor(bars),
                "relative_strength": relative_strength_factor(bars, bars),
                "liquidity": liquidity_factor(bars),
            }
            score, _, _ = composite_score(factors, cfg)
            d = decide(score, 50.0, reg, ent, cfg)
            labels.append(d.label)
        assert_label_distribution(labels, min_entropy=0.5)


if __name__ == "__main__":
    unittest.main()
