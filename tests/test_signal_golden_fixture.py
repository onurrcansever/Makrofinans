# -*- coding: utf-8 -*-
"""Golden fixture bütünlüğü — hacim verisi ve panel skorları."""
from __future__ import annotations

import json
import pickle
import unittest
import unittest.mock
import os
from pathlib import Path

import pandas as pd

from signal_engine.data.bars import (
    BarSeries, _extract_volume, pct_change_window_info, _extract_close,
    pct_change_n, pct_change_calendar,
)
from signal_engine.factors.compute import relative_strength_factor
from signal_engine.pipeline import signal_engine_v2_uygula
from signal_engine.decisions.history import clear_decision_history
from fiyat_para import tablo_getiri, tablo_fiyat, assert_fx_cross_sanity
from stock_scanner import _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
META = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"


def _load():
    with FIX.open("rb") as f:
        blob = pickle.load(f)
    with META.open(encoding="utf-8") as f:
        meta = json.load(f)
    return blob["df"], blob["snap"], meta["golden"]


class GoldenFixtureIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, cls.snap_vals, cls.golden = _load()

    def test_fixture_carries_real_volume_not_constant_placeholder(self):
        """Sabit 1M hacim veya tüm sembollerde v20/v60≈1.0 — fixture dondurma hatası."""
        ratios = []
        for sym in ("AMAT", "CSCO", "MSFT", "EQQQ.L"):
            vol = _extract_volume(self.df, sym)
            self.assertIsNotNone(vol, msg=f"{sym}: Volume sütunu yok")
            self.assertFalse(vol.empty, msg=f"{sym}: Volume boş")
            self.assertFalse(
                (vol == 1_000_000).all(),
                msg=f"{sym}: hacim sabit 1M — fixture dondurma hatası",
            )
            v20 = float(vol.tail(20).mean())
            v60 = float(vol.tail(60).mean())
            self.assertGreater(v60, 0, msg=f"{sym}: v60=0")
            ratios.append(v20 / v60)
        # Tek varlıkta v20/v60≈1.0 meşru; tüm fixture nötrse dondurma hatası.
        neutral = sum(1 for r in ratios if abs(r - 1.0) < 0.02)
        self.assertLess(
            neutral, len(ratios),
            msg="Tüm sembollerde v20/v60≈1.0 — hacim serisi donmamış olabilir",
        )


class GoldenPanelScoresTest(unittest.TestCase):
    """15 Tem 2026 panel referans skorları — fixture üzerinde deterministik."""

    @classmethod
    def setUpClass(cls):
        cls._hist_path = os.environ.get("DECISION_HISTORY_PATH")
        cls._tmp_hist = Path(__file__).resolve().parent / ".tmp_golden_decision_history.json"
        os.environ["DECISION_HISTORY_PATH"] = str(cls._tmp_hist)
        import signal_engine.decisions.history as dh
        dh.STATE_PATH = str(cls._tmp_hist)
        clear_decision_history()

        cls.df, cls.snap_vals, cls.golden = _load()
        from macro_data import MacroSnapshot
        from decision_engine import PiyasaVerisi
        from etf_universe import REVOLUT_ETFLER

        cls.snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=cls.snap_vals["eur_try"],
            usd_try=cls.snap_vals["usd_try"],
        ))
        cls.etf = {x[0]: x for x in REVOLUT_ETFLER}

    @classmethod
    def tearDownClass(cls):
        clear_decision_history()
        if cls._tmp_hist.exists():
            cls._tmp_hist.unlink()
        if cls._hist_path is None:
            os.environ.pop("DECISION_HISTORY_PATH", None)
        else:
            os.environ["DECISION_HISTORY_PATH"] = cls._hist_path
        import signal_engine.decisions.history as dh
        dh.STATE_PATH = os.environ.get("DECISION_HISTORY_PATH", ".decision_history.json")

    def _run(self, sym: str):
        clear_decision_history()
        if sym in self.etf:
            t = self.etf[sym]
            h = _hisse_analiz(
                self.df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
                isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
            )
        else:
            h = _hisse_analiz(self.df, sym, sym, "NASDAQ", "teknoloji", "NOTR", self.snap)
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula([h], self.df, profil_risk="orta", persist_decision_history=False)
        return h

    def _assert_panel(self, sym: str):
        h = self._run(sym)
        exp = self.golden[sym]
        self.assertAlmostEqual(
            float(h.signal_v2_score), float(exp["score"]), delta=0.6, msg=f"{sym} skor",
        )
        for k, v in exp["factors"].items():
            self.assertAlmostEqual(h.signal_v2_factors[k], float(v), delta=0.6, msg=f"{sym}.{k}")
        if "decision" in exp:
            self.assertEqual(h.signal_v2_decision, exp["decision"])

    def test_amat_panel(self):
        self._assert_panel("AMAT")

    def test_csco_panel(self):
        self._assert_panel("CSCO")

    def test_msft_panel(self):
        self._assert_panel("MSFT")

    def test_eqqq_panel(self):
        self._assert_panel("EQQQ.L")

    def test_veur_panel(self):
        """VEUR 66→AL artefaktı — settlement asof pin (İZLE, ≤64 bandı)."""
        self._assert_panel("VEUR.L")
        h = self._run("VEUR.L")
        self.assertLess(h.signal_v2_score, 66.0)
        self.assertEqual(h.signal_v2_decision, "İZLE")


class RelAlphaWindowTest(unittest.TestCase):
    """EQQQ 3M=6M α — aynı pencere değil; farklı başlangıç tarihleri."""

    @classmethod
    def setUpClass(cls):
        cls.df, _, _ = _load()

    def test_eqqq_3m_6m_windows_have_different_starts(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        w3 = pct_change_window_info(bars.close, 63)
        w6 = pct_change_window_info(bars.close, 126)
        self.assertIsNotNone(w3)
        self.assertIsNotNone(w6)
        self.assertGreater(w3["start_date"], w6["start_date"])
        self.assertNotEqual(w3["start_date"], w6["start_date"])

    def test_amat_3m_6m_windows_differ_control(self):
        bars = BarSeries.from_df(self.df, "AMAT")
        w3 = pct_change_window_info(bars.close, 63)
        w6 = pct_change_window_info(bars.close, 126)
        self.assertGreater(w3["start_date"], w6["start_date"])

    def test_eqqq_fx_adjusted_alpha_3m_ne_6m(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        bench = BarSeries.from_df(self.df, "^GSPC")
        rs = relative_strength_factor(bars, bench, df=self.df, bench_symbol="^GSPC")
        self.assertIn("3M α", rs.detail)
        self.assertIn("6M α", rs.detail)
        d3 = float(rs.detail.split("3M α")[1].split("pp")[0].replace("+", "").strip())
        d6 = float(rs.detail.split("6M α")[1].split("pp")[0].replace("+", "").strip())
        self.assertNotAlmostEqual(d3, d6, places=2)


class RelStrengthFxConversionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, _, _ = _load()

    def test_usd_asset_unchanged_by_fx(self):
        bars = BarSeries.from_df(self.df, "AMAT")
        bench = BarSeries.from_df(self.df, "^IXIC")
        plain = relative_strength_factor(bars, bench, df=self.df, bench_symbol="^IXIC")
        self.assertAlmostEqual(plain.score, 75.0, delta=0.5)

    def test_gbp_etf_uses_fx_converted_benchmark(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        bench = BarSeries.from_df(self.df, "^GSPC")
        fx = relative_strength_factor(bars, bench, df=self.df, bench_symbol="^GSPC")
        raw = relative_strength_factor(bars, bench)
        self.assertNotAlmostEqual(fx.score, raw.score, delta=0.3)
        self.assertIn("+4.6", fx.detail.split("3M")[1][:8])


class GoldenTlPresentationTest(unittest.TestCase):
    """Fixture USDTRY/EURTRY ile dondurulmuş TL sunum katmanı."""

    @classmethod
    def setUpClass(cls):
        cls.df, cls.snap_vals, cls.golden = _load()

    def test_fixture_has_usdtry_series(self):
        ut = _extract_close(self.df, "USDTRY=X")
        self.assertFalse(ut.empty)

    def test_eqqq_tl_presentation_matches_golden(self):
        exp = self.golden["EQQQ.L"]
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        ut = _extract_close(self.df, "USDTRY=X")
        gbp_fx = _extract_close(self.df, "GBPUSD=X")
        et = _extract_close(self.df, "EURTRY=X")
        d1y = pct_change_calendar(bars.close, 365)
        d1a = pct_change_n(bars.close, 21)
        tl_1y = tablo_getiri(d1y, "TL", 252, et, ut, gbp_seri=gbp_fx, asset_pb="GBP", bar_dates=bars.close.index)
        tl_1a = tablo_getiri(d1a, "TL", 21, et, ut, gbp_seri=gbp_fx, asset_pb="GBP", bar_dates=bars.close.index)
        tl_12_1 = ((1 + tl_1y / 100) / (1 + tl_1a / 100) - 1) * 100
        self.assertAlmostEqual(tl_1y, exp["getiri_1y_tl_pct"], delta=0.15)
        self.assertAlmostEqual(tl_12_1, exp["momentum_12_1_tl_pct"], delta=0.15)
        if "getiri_1y_usd_pct" in exp:
            usd_1y = tablo_getiri(
                d1y, "USD", 252, et, ut, gbp_seri=gbp_fx, asset_pb="GBP",
                bar_dates=bars.close.index,
            )
            self.assertAlmostEqual(usd_1y, exp["getiri_1y_usd_pct"], delta=0.15)
        gbp_px = float(bars.close.iloc[-1])
        usd_end = float(ut.iloc[-1])
        eur_end = float(et.iloc[-1])
        gbp_end = float(gbp_fx.iloc[-1])
        tl_px = tablo_fiyat(
            gbp_px, "TL", eur_end, usd_end,
            sembol="EQQQ.L", quote_currency="GBP",
            gbp_usd=gbp_end,
        )
        assert_fx_cross_sanity(
            usd_try=usd_end,
            gbp_usd=gbp_end,
            gbp_settlement=gbp_px,
            tl_price=tl_px,
            label="EQQQ.L fixture",
        )


if __name__ == "__main__":
    unittest.main()
