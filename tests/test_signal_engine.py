# -*- coding: utf-8 -*-
"""Signal Engine v2 testleri."""
import unittest

import numpy as np
import pandas as pd

from signal_engine.backtest.signal_backtest import assert_no_lookahead, run_signal_backtest
from signal_engine.config.loader import load_signal_config
from signal_engine.data.bars import BarSeries
from signal_engine.entry.levels import compute_entry, historical_p_fill
from signal_engine.factors.compute import trend_factor, mean_reversion_factor
from signal_engine.regime.classifier import classify_regime
from signal_engine.scoring.composite import composite_score, percentile_within_class


def _trend_up(n=300, start=100.0, drift=0.0008):
    rng = np.random.default_rng(42)
    rets = rng.normal(drift, 0.008, n)
    prices = start * np.cumprod(1 + rets)
    return pd.Series(prices)


class SignalEngineTest(unittest.TestCase):
    def test_config_loads(self):
        cfg = load_signal_config()
        self.assertAlmostEqual(sum(cfg.weights.values()), 1.0, places=2)

    def test_trend_factor_range(self):
        bars = BarSeries.from_series(_trend_up())
        r = trend_factor(bars)
        self.assertTrue(r.available)
        self.assertGreaterEqual(r.score, 0)
        self.assertLessEqual(r.score, 100)

    def test_regime_trending_up(self):
        bars = BarSeries.from_series(_trend_up())
        reg = classify_regime(bars, load_signal_config())
        self.assertIn(reg.regime, ("TRENDING_UP", "RANGE_BOUND", "HIGH_VOL"))

    def test_entry_structure_levels(self):
        close = _trend_up(400)
        bars = BarSeries.from_series(close)
        price = float(close.iloc[-1])
        ent = compute_entry(bars, "TRENDING_UP", load_signal_config())
        self.assertIsNotNone(ent.price)
        self.assertLess(ent.price, price)
        self.assertGreater(ent.price, price * 0.85)

    def test_entry_not_25pct_in_uptrend(self):
        close = _trend_up()
        bars = BarSeries.from_series(close)
        price = float(close.iloc[-1])
        ent = compute_entry(bars, "TRENDING_UP", load_signal_config())
        self.assertGreater(ent.price, price * 0.85)

    def test_p_fill_bounded(self):
        close = _trend_up(800)
        p = historical_p_fill(close, float(close.iloc[-1]) * 0.95, 90)
        if p is not None:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_composite_renormalizes_missing(self):
        cfg = load_signal_config()
        from signal_engine.factors.compute import FactorResult
        factors = {
            "trend": FactorResult(70, True),
            "mean_reversion": FactorResult(50, False),
            "volatility": FactorResult(60, True),
            "relative_strength": FactorResult(55, False),
            "liquidity": FactorResult(50, False),
        }
        score, used, total = composite_score(factors, cfg)
        self.assertEqual(used, 2)
        self.assertGreater(score, 0)

    def test_percentile_spread(self):
        vals = [55, 60, 65, 70, 75]
        p = [percentile_within_class(vals, v) for v in vals]
        self.assertEqual(p[0], 10.0)
        self.assertEqual(p[-1], 90.0)

    def test_no_lookahead(self):
        close = _trend_up(200)
        self.assertTrue(assert_no_lookahead(close))

    def test_backtest_runs(self):
        close = _trend_up(500)
        rows = run_signal_backtest(close)
        self.assertTrue(len(rows) >= 1)

    def test_etf_meta_known(self):
        from signal_engine.data.etf_quality import etf_meta
        m = etf_meta("IE00B5BMR087")  # CSPX
        self.assertIsNotNone(m)
        self.assertIn("aum_bn_eur", m)

    def test_why_markdown(self):
        from signal_engine.explain.why import why_markdown
        from stock_scanner import HisseAnaliz
        h = HisseAnaliz(
            sembol="CSPX.L", ad="CSPX", piyasa="ETF",
            fiyat=100.0, degisim_1g=0.0, degisim_1ay=1.0, degisim_3ay=2.0, degisim_1y=5.0,
            rsi=55.0, sma20=99.0, sma50=98.0, sinyal="BEKLE", skor=72.0, gerekce="test",
        )
        h.signal_v2_score = 72.0
        h.signal_v2_percentile = 80.0
        h.signal_v2_decision = "AL"
        h.signal_v2_code = "BUY"
        h.signal_v2_regime = "TRENDING_UP"
        h.signal_v2_regime_detail = ""
        h.signal_v2_al_method = "—"
        h.signal_v2_data = "5/5"
        h.signal_v2_factors = {"trend": 75.0}
        h.signal_v2_factor_details = {"trend": "SMA50>200"}
        h.signal_v2_why = "Skor 72 (sınıf %50) · stale"
        md = why_markdown(h)
        self.assertIn("AL", md)
        self.assertIn("Trend", md)
        self.assertIn("sınıf %80", md)
        self.assertNotIn("sınıf %50", md)

    def test_sparkline_length(self):
        from signal_engine.scoring.sparkline import compute_score_sparkline
        from signal_engine.data.bars import BarSeries
        close = _trend_up(400)
        bars = BarSeries.from_series(close)
        bench = BarSeries.from_series(close * 0.98)
        cfg = load_signal_config()
        sp = compute_score_sparkline(bars, bench, cfg)
        self.assertGreaterEqual(len(sp), 2)


if __name__ == "__main__":
    unittest.main()
