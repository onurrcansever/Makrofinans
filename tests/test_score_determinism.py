# -*- coding: utf-8 -*-
"""Skor determinizmi — aynı bar → aynı skor; LSE-ahead / FX spot sızması yok."""
from __future__ import annotations

import pickle
import unittest
import unittest.mock
from pathlib import Path

import pandas as pd

from signal_engine.data.bars import BarSeries, settlement_asof, truncate_bars_to_asof
from signal_engine.factors.compute import relative_strength_factor
from signal_engine.pipeline import signal_engine_v2_uygula
from stock_scanner import _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"


class ScoreDeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIX.open("rb") as f:
            blob = pickle.load(f)
        cls.df = blob["df"]
        from macro_data import MacroSnapshot
        from decision_engine import PiyasaVerisi

        snap = blob["snap"]
        cls.snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=snap["eur_try"], usd_try=snap["usd_try"],
        ))

    def _run_eqqq(self, df):
        from etf_universe import REVOLUT_ETFLER

        t = next(x for x in REVOLUT_ETFLER if x[0] == "EQQQ.L")
        h = _hisse_analiz(
            df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
            isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
        )
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula([h], df, profil_risk="orta", persist_decision_history=False)
        return h

    def test_same_fixture_twice_identical_score(self):
        h1 = self._run_eqqq(self.df)
        h2 = self._run_eqqq(self.df)
        self.assertEqual(h1.signal_v2_score, h2.signal_v2_score)
        self.assertEqual(h1.signal_v2_factors, h2.signal_v2_factors)

    def test_fx_spot_after_asof_does_not_change_rs(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        bench = BarSeries.from_df(self.df, "^GSPC")
        rs0 = relative_strength_factor(bars, bench, df=self.df, bench_symbol="^GSPC")

        df2 = self.df.copy()
        last = df2.index[-1]
        newer = last + pd.Timedelta(days=1)
        # Sonraki takvim gününe sahte GBPUSD ekle (canlı spot)
        if isinstance(df2.columns, pd.MultiIndex):
            col = ("GBPUSD=X", "Close")
            if col in df2.columns:
                df2.loc[newer, col] = float(df2[col].dropna().iloc[-1]) * 1.05

        bars2 = BarSeries.from_df(df2, "EQQQ.L")
        bench2 = BarSeries.from_df(df2, "^GSPC")
        asof = settlement_asof(bars2, bench2, df2)
        bars2 = truncate_bars_to_asof(bars2, asof)
        bench2 = truncate_bars_to_asof(bench2, asof)
        rs1 = relative_strength_factor(bars2, bench2, df=df2, bench_symbol="^GSPC")
        self.assertAlmostEqual(rs0.score, rs1.score, places=4)

    def test_lse_bar_after_us_asof_does_not_change_eqqq_score(self):
        """Rapor 65 vs golden 64 — LSE 16 Tem bar'ı skor dışı kalmalı."""
        from signal_engine.data.bars import _extract_close

        h0 = self._run_eqqq(self.df)
        raw = _extract_close(self.df, "EQQQ.L")
        last = raw.index[-1]
        newer = last + pd.Timedelta(days=1)
        # Ham kotasyon GBp (pence); settlement GBP enjekte etmek karantinaya düşürür
        raw_last = float(raw.iloc[-1])
        df2 = self.df.copy().reindex(self.df.index.union([newer]))
        if isinstance(df2.columns, pd.MultiIndex):
            for field in ("Open", "High", "Low", "Close"):
                col = ("EQQQ.L", field)
                if col in df2.columns:
                    df2.loc[newer, col] = raw_last * 1.02
            vol_col = ("EQQQ.L", "Volume")
            if vol_col in df2.columns:
                df2.loc[newer, vol_col] = 1_000_000.0
        eq2 = BarSeries.from_df(df2, "EQQQ.L")
        bench2 = BarSeries.from_df(df2, "^GSPC")
        self.assertFalse(eq2.quarantine)
        self.assertGreater(eq2.close.index[-1], bench2.close.index[-1])
        h1 = self._run_eqqq(df2)
        self.assertEqual(h0.signal_v2_score, h1.signal_v2_score)
        self.assertEqual(h0.signal_v2_factors, h1.signal_v2_factors)


class AmatEurReturnEvidenceTest(unittest.TestCase):
    """1Y EUR ≠ native — rapor3 artefaktı (FX=1) yasak."""

    @classmethod
    def setUpClass(cls):
        with FIX.open("rb") as f:
            cls.df = pickle.load(f)["df"]

    def test_amat_1y_eur_not_native_and_endpoints_aligned(self):
        from fiyat_para import getiri_kur_ayarli, _fx_endpoints_for_window
        from fiyat_para_fx import fx_window_dates, fx_value_at
        from signal_engine.data.bars import BarSeries, pct_change_n, _extract_close

        bars = BarSeries.from_df(self.df, "AMAT")
        d1y = pct_change_n(bars.close, 252)
        et = _extract_close(self.df, "EURTRY=X")
        ut = _extract_close(self.df, "USDTRY=X")
        gbp = _extract_close(self.df, "GBPUSD=X")
        from signal_engine.data.bars import pct_change_calendar

        d0, d1 = fx_window_dates(bars.close.index, 252)
        self.assertEqual(str(d1.date()), "2026-07-15")
        # 1Y = takvim 365g — d0 ≈ 2025-07-15 (±1)
        self.assertAlmostEqual((d1 - d0).days, 365, delta=5)
        fx = _fx_endpoints_for_window(252, et, ut, gbp, bar_dates=bars.close.index)
        self.assertEqual(str(pd.Timestamp(fx["end_date"]).date()), "2026-07-15")
        d1y_cal = pct_change_calendar(bars.close, 365)
        r_eur = getiri_kur_ayarli(
            d1y_cal, "USD", "EUR", 252, et, ut, gbp, bar_dates=bars.close.index,
        )
        factor = (fx["usd_end"] / fx["usd_start"]) * (fx["eur_start"] / fx["eur_end"])
        self.assertNotAlmostEqual(r_eur, d1y_cal, delta=0.5)
        self.assertGreater(factor, 0.95)
        self.assertLess(factor, 1.08)

    def test_eqqq_1y_endpoints_gbp_eur(self):
        from fiyat_para import getiri_kur_ayarli, _fx_endpoints_for_window
        from fiyat_para_fx import fx_window_dates
        from signal_engine.data.bars import BarSeries, pct_change_n, _extract_close

        bars = BarSeries.from_df(self.df, "EQQQ.L")
        d1y = pct_change_n(bars.close, 252)
        et = _extract_close(self.df, "EURTRY=X")
        ut = _extract_close(self.df, "USDTRY=X")
        gbp = _extract_close(self.df, "GBPUSD=X")
        eurusd = _extract_close(self.df, "EURUSD=X")
        d0, d1 = fx_window_dates(bars.close.index, 252)
        fx = _fx_endpoints_for_window(252, et, ut, gbp, bar_dates=bars.close.index)
        self.assertEqual(pd.Timestamp(fx["start_date"]).date(), d0.date())
        self.assertEqual(pd.Timestamp(fx["end_date"]).date(), d1.date())
        from fiyat_para_fx import fx_value_at
        print(
            f"EQQQ 1Y endpoints: {d0.date()} -> {d1.date()} | "
            f"GBPUSD {fx_value_at(gbp, d0):.6f}->{fx_value_at(gbp, d1):.6f} | "
            f"EURUSD {fx_value_at(eurusd, d0):.6f}->{fx_value_at(eurusd, d1):.6f} | "
            f"USDTRY {fx['usd_start']:.4f}->{fx['usd_end']:.4f} | "
            f"EURTRY {fx['eur_start']:.4f}->{fx['eur_end']:.4f}"
        )
        r_eur = getiri_kur_ayarli(d1y, "GBP", "EUR", 252, et, ut, gbp, bar_dates=bars.close.index)
        self.assertIsNotNone(r_eur)
        self.assertNotAlmostEqual(r_eur, d1y, delta=0.5)

    def test_silent_native_fallback_removed(self):
        from fiyat_para import getiri_kur_ayarli
        from fiyat_para_fx import FxUnavailableError

        idx = pd.date_range("2026-01-01", periods=10, freq="B")
        et = pd.Series(50.0, index=idx)
        ut = pd.Series(45.0, index=idx)
        with self.assertRaises(FxUnavailableError):
            getiri_kur_ayarli(10.0, "USD", "EUR", 252, et, ut, bar_dates=idx)


if __name__ == "__main__":
    unittest.main()
