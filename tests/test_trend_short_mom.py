# -*- coding: utf-8 -*-
"""Kısa momentum — flag kapalıyken regresyon + preset ayarı."""
from __future__ import annotations

import unittest

import pandas as pd

from signal_engine.data.bars import BarSeries
from signal_engine.factors.compute import (
    resolve_short_mom_preset,
    short_mom_adjustment,
    trend_factor,
)


def _synth_close(n: int = 300, end: float = 100.0) -> pd.Series:
    # Yavaş yükseliş + son 63 günde %15 toparlanma
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    vals = [50.0 + i * 0.05 for i in range(n)]
    # Son 63 iş gününde belirgin yükseliş
    for j in range(63):
        vals[-(63 - j)] = vals[-(63 - j)] * (1.0 + 0.0025 * (j + 1) / 63)
    vals[-1] = end
    return pd.Series(vals, index=idx)


class ShortMomTest(unittest.TestCase):
    def test_flag_off_matches_explicit_off(self):
        c = _synth_close()
        bars = BarSeries.from_series(c)
        a = trend_factor(bars, apply_short_mom=False).score
        b = trend_factor(
            bars,
            apply_short_mom=False,
            short_mom_cfg={"enabled": False},
        ).score
        self.assertEqual(a, b)

    def test_temkinli_can_raise_vs_off(self):
        c = _synth_close(end=120.0)
        bars = BarSeries.from_series(c)
        off = trend_factor(bars, apply_short_mom=False).score
        on = trend_factor(
            bars,
            apply_short_mom=True,
            short_mom_preset="temkinli",
            short_mom_cfg={"enabled": True, "preset": "temkinli"},
        ).score
        # Toparlanma serisinde on ≥ off beklenir
        self.assertGreaterEqual(on, off)

    def test_preset_resolve(self):
        p = resolve_short_mom_preset("temkinli")
        self.assertIsNotNone(p)
        self.assertEqual(p["m3_hi"][1], 6.0)
        self.assertIsNone(resolve_short_mom_preset("off"))


if __name__ == "__main__":
    unittest.main()
