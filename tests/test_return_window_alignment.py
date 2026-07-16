# -*- coding: utf-8
"""Getiri pencereleri — bar offset vs takvim günü kayması."""
from __future__ import annotations

import pickle
import unittest

import pandas as pd

from signal_engine.data.bars import BarSeries, pct_change_n


class ReturnWindowAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("tests/fixtures/signal_golden_20260715.pkl", "rb") as f:
            cls.df = pickle.load(f)["df"]
        cls.bars = BarSeries.from_df(cls.df, "EQQQ.L")
        cls.close = cls.bars.close

    def test_1y_uses_calendar_365_not_252_bar_offset(self):
        from fiyat_para_fx import fx_window_dates_calendar
        from signal_engine.data.bars import pct_change_calendar

        d0_bar = self.close.index[-253]
        d1 = self.close.index[-1]
        d0_cal, d1_cal = fx_window_dates_calendar(self.close.index, 365)
        self.assertEqual(d1_cal, d1)
        self.assertNotEqual(d0_cal.date(), d0_bar.date())
        self.assertAlmostEqual((d1 - d0_cal).days, 365, delta=5)
        r_cal = pct_change_calendar(self.close, 365)
        self.assertIsNotNone(r_cal)

    def test_native_windows_short_are_bar_offset(self):
        for gun, label in [(21, "1M"), (63, "3M"), (126, "6M")]:
            r = pct_change_n(self.close, gun)
            start = float(self.close.iloc[-gun - 1])
            end = float(self.close.iloc[-1])
            implied = (end / start - 1) * 100
            self.assertAlmostEqual(r, implied, places=2, msg=label)


if __name__ == "__main__":
    unittest.main()
