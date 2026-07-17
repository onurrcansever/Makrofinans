# -*- coding: utf-8 -*-
"""1G % — resmi previousClose; history boşluğunda bar[-2] kullanılmaz."""
from __future__ import annotations

import unittest

import pandas as pd

from fiyat_para_fx import fx_window_dates
from stock_scanner import _degisim, _degisim_1g


class Degisim1gPreviousCloseTest(unittest.TestCase):
    def test_mgros_gap_uses_previous_close_not_bar_minus_2(self):
        # Yahoo history: 14 Tem 608, 15–16 eksik, 17 Tem 641.5
        # Resmi previousClose: 627 (Google ile aynı)
        idx = pd.to_datetime(["2026-07-13", "2026-07-14", "2026-07-17"])
        close = pd.Series([626.0, 608.0, 641.5], index=idx)
        bar_based = _degisim(close, 1)
        self.assertAlmostEqual(bar_based, (641.5 - 608.0) / 608.0 * 100, places=2)

        official = _degisim_1g(641.5, close, previous_close=627.0)
        self.assertAlmostEqual(official, (641.5 - 627.0) / 627.0 * 100, places=2)
        self.assertAlmostEqual(official, 2.31, places=2)
        self.assertNotAlmostEqual(official, bar_based, places=1)

    def test_fallback_without_previous_close(self):
        idx = pd.to_datetime(["2026-07-13", "2026-07-14", "2026-07-15"])
        close = pd.Series([100.0, 110.0, 121.0], index=idx)
        self.assertAlmostEqual(_degisim_1g(121.0, close, None), 10.0, places=4)

    def test_gap_without_previous_close_returns_none(self):
        idx = pd.to_datetime(["2026-07-14", "2026-07-17"])
        close = pd.Series([608.0, 641.5], index=idx)
        self.assertIsNone(_degisim_1g(641.5, close, None))
        self.assertAlmostEqual(
            _degisim_1g(641.5, close, 627.0),
            (641.5 - 627.0) / 627.0 * 100,
            places=2,
        )

    def test_fx_window_1g_rejects_multi_day_gap(self):
        idx = pd.to_datetime(["2026-07-14", "2026-07-17"])
        self.assertIsNone(fx_window_dates(pd.DatetimeIndex(idx), 1))

    def test_fx_window_1g_accepts_adjacent_session(self):
        idx = pd.to_datetime(["2026-07-16", "2026-07-17"])
        pair = fx_window_dates(pd.DatetimeIndex(idx), 1)
        self.assertIsNotNone(pair)
        d0, d1 = pair
        self.assertEqual(d0.date().isoformat(), "2026-07-16")
        self.assertEqual(d1.date().isoformat(), "2026-07-17")


if __name__ == "__main__":
    unittest.main()
