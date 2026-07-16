# -*- coding: utf-8
"""Signal Engine — para birimi tutarlılığı ve dondurulmuş golden skorlar."""
from __future__ import annotations

import json
import pickle
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
import pandas as pd

from signal_engine.data.bars import BarSeries, momentum_12_1, pct_change_window_info
from signal_engine.data.lineage import trace_price_lineage
from signal_engine.factors.compute import relative_strength_factor, trend_factor
from signal_engine.pipeline import signal_engine_v2_uygula
from stock_scanner import _close_al_with_meta, _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
META = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"


def _load_fixture():
    with FIX.open("rb") as f:
        blob = pickle.load(f)
    with META.open(encoding="utf-8") as f:
        meta = json.load(f)
    return blob["df"], blob["snap"], meta["golden"]


def _synthetic_usd_trend(n=320, start=100.0, drift=0.0015):
    rng = np.random.default_rng(7)
    prices = start * np.cumprod(1 + rng.normal(drift, 0.01, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(prices, index=idx)


def _df_from_closes(mapping: dict) -> pd.DataFrame:
    frames = {}
    for sym, ser in mapping.items():
        frames[(sym, "Close")] = ser
        frames[(sym, "Volume")] = pd.Series(1_000_000, index=ser.index)
    return pd.DataFrame(frames)


class SignalCurrencyTest(unittest.TestCase):
    def test_bars_from_df_uses_yahoo_source_currency(self):
        ser = pd.Series([52000.0, 53000.0, 54000.0], index=pd.date_range("2024-01-01", periods=3, freq="D"))
        df = _df_from_closes({"EQQQ.L": ser})
        with unittest.mock.patch(
            "signal_engine.data.quote_normalize.fetch_source_quote_currency",
            return_value="GBp",
        ):
            bars = BarSeries.from_df(df, "EQQQ.L")
        self.assertEqual(bars.settlement_currency, "GBP")
        self.assertAlmostEqual(float(bars.close.iloc[-1]), 540.0)

    def test_engine_matches_scanner_close_series(self):
        ser = pd.Series(np.linspace(400, 520, 280), index=pd.date_range("2024-01-01", periods=280, freq="B"))
        df = _df_from_closes({"TEST.L": ser, "^GSPC": ser * 0.95})
        close_scanner, meta = _close_al_with_meta(df, "TEST.L")
        bars = BarSeries.from_df(df, "TEST.L")
        pd.testing.assert_series_equal(
            close_scanner.astype(float),
            bars.close.astype(float),
            check_names=False,
        )
        self.assertEqual(bars.settlement_currency, meta.settlement_currency)

    def test_tl_overlay_changes_momentum_more_than_2pct(self):
        usd = _synthetic_usd_trend()
        usdtry = pd.Series(np.linspace(30.0, 40.0, len(usd)), index=usd.index)
        tl = usd * usdtry
        mom_usd = momentum_12_1(usd)
        mom_tl = momentum_12_1(tl)
        self.assertIsNotNone(mom_usd)
        self.assertIsNotNone(mom_tl)
        self.assertGreater(abs(mom_tl - mom_usd), 2.0)

    def test_trend_score_invariant_to_uniform_fx_scale(self):
        usd = _synthetic_usd_trend()
        bars_usd = BarSeries.from_series(usd, settlement_currency="USD")
        bars_scaled = BarSeries.from_series(usd * 57.0, settlement_currency="USD")
        self.assertAlmostEqual(trend_factor(bars_usd).score, trend_factor(bars_scaled).score, places=4)


class SignalGoldenFrozenTest(unittest.TestCase):
    """2026-07-15 kapanış fixture — canlı Yahoo yok."""

    @classmethod
    def setUpClass(cls):
        cls.df, cls.snap_vals, cls.golden = _load_fixture()
        from macro_data import MacroSnapshot
        from decision_engine import PiyasaVerisi
        from etf_universe import REVOLUT_ETFLER

        cls.snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=cls.snap_vals["eur_try"],
            usd_try=cls.snap_vals["usd_try"],
        ))
        cls.etf = {x[0]: x for x in REVOLUT_ETFLER}

    def _run(self, sym: str):
        if sym == "EQQQ.L":
            t = self.etf[sym]
            h = _hisse_analiz(
                self.df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
                isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
            )
        else:
            h = _hisse_analiz(self.df, sym, sym, "NASDAQ", "teknoloji", "NOTR", self.snap)
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula([h], self.df, profil_risk="orta")
        return h

    def test_golden_fixture_amat(self):
        h = self._run("AMAT")
        exp = self.golden["AMAT"]
        self.assertEqual(h.signal_v2_decision, exp["decision"])
        for k, v in exp["factors"].items():
            self.assertAlmostEqual(h.signal_v2_factors[k], float(v), delta=0.6, msg=k)
        self.assertEqual(round(h.signal_v2_score), exp["score"])

    def test_golden_fixture_csco(self):
        h = self._run("CSCO")
        exp = self.golden["CSCO"]
        for k, v in exp["factors"].items():
            self.assertAlmostEqual(h.signal_v2_factors[k], float(v), delta=0.6, msg=k)
        self.assertEqual(round(h.signal_v2_score), exp["score"])

    def test_golden_fixture_msft(self):
        h = self._run("MSFT")
        exp = self.golden["MSFT"]
        for k, v in exp["factors"].items():
            self.assertAlmostEqual(h.signal_v2_factors[k], float(v), delta=0.6, msg=k)
        self.assertEqual(round(h.signal_v2_score), exp["score"])

    def test_golden_fixture_eqqq_not_at_al_threshold(self):
        """Fixture: skor 64 < AL 66 — histerezis/bug3 öncesi AL'a dönmemeli."""
        h = self._run("EQQQ.L")
        exp = self.golden["EQQQ.L"]
        self.assertEqual(h.signal_v2_code, "WATCH")
        self.assertEqual(h.signal_v2_decision, "İZLE")
        self.assertEqual(round(h.signal_v2_score), exp["score"])
        self.assertAlmostEqual(h.signal_v2_factors["mean_reversion"], float(exp["factors"]["mean_reversion"]), delta=0.6)
        self.assertAlmostEqual(h.signal_v2_factors["trend"], float(exp["factors"]["trend"]), delta=0.6)

    def test_eqqq_jul15_momentum_12_1_gbp(self):
        exp = self.golden["EQQQ.L"]["momentum_12_1_gbp_pct"]
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        mom = momentum_12_1(bars.close)
        self.assertAlmostEqual(mom, exp, places=2)
        self.assertAlmostEqual(mom, 32.70, places=1)

    def test_eqqq_rel_alpha_3m_6m_different_windows_not_copy(self):
        """Ham α farklı pencerelerden; EQQQ'da tesadüfen yakın (FX-düzeltilmiş)."""
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        bench = BarSeries.from_df(self.df, "^GSPC")
        w3a = pct_change_window_info(bars.close, 63)
        w6a = pct_change_window_info(bars.close, 126)
        self.assertNotEqual(w3a["start_date"], w6a["start_date"])
        rs = relative_strength_factor(bars, bench, df=self.df, bench_symbol="^GSPC")
        self.assertIn("3M α", rs.detail)
        self.assertIn("6M α", rs.detail)
        from signal_engine.data.fx_series import benchmark_close_in_settlement
        bc = benchmark_close_in_settlement(bench.close, "GBP", self.df).reindex(bars.close.index, method="ffill")
        from signal_engine.data.bars import pct_change_n
        d3 = pct_change_n(bars.close, 63) - pct_change_n(bc, 63)
        d6 = pct_change_n(bars.close, 126) - pct_change_n(bc, 126)
        self.assertNotAlmostEqual(d3, d6, places=1)

    def test_lineage_settlement_not_tl(self):
        info = trace_price_lineage(self.df, "EQQQ.L")
        self.assertEqual(info["settlement_currency"], "GBP")
        self.assertAlmostEqual(info["momentum_12_1_settlement_pct"], 32.70, places=1)


if __name__ == "__main__":
    unittest.main()
