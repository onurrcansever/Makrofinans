# -*- coding: utf-8
"""15 Tem 2026 fixture — GBP/USD/TL sütun çapraz tutarlılığı (%0.1)."""
from __future__ import annotations

import json
import pickle
import unittest
from types import SimpleNamespace

import pandas as pd

from decision_engine import PiyasaVerisi
from fiyat_para import tablo_fiyat, tablo_getiri
from fiyat_para_fx import assert_price_cross_consistency, kur_tablo_spot
from macro_data import MacroSnapshot
from signal_engine.data.bars import BarSeries, pct_change_n, _extract_close
from stock_scanner import _hisse_analiz, _indir


FIX = "tests/fixtures/signal_golden_20260715.pkl"
META = "tests/fixtures/signal_golden_20260715.json"
ASOF = pd.Timestamp("2026-07-15")


def _snap_and_fx(df):
    with open(META, encoding="utf-8") as f:
        snap_vals = json.load(f)["snap"]
    snap = MacroSnapshot(veri=PiyasaVerisi(
        eur_try=snap_vals["eur_try"], usd_try=snap_vals["usd_try"],
    ))
    et = _extract_close(df, "EURTRY=X")
    ut = _extract_close(df, "USDTRY=X")
    gbp = _extract_close(df, "GBPUSD=X")
    eurusd = _extract_close(df, "EURUSD=X")
    fx = kur_tablo_spot(snap, et, ut, gbp, eurusd, asof=ASOF)
    return snap, fx, et, ut, gbp


class Jul15CrossConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIX, "rb") as f:
            cls.df = pickle.load(f)["df"]
        cls.snap, cls.fx, cls.et, cls.ut, cls.gbp = _snap_and_fx(cls.df)

    def _columns(self, sym: str, *, piyasa="ETF", varlik_turu="etf"):
        bars = BarSeries.from_df(self.df, sym)
        gbp_px = float(bars.close.loc[:ASOF].iloc[-1])
        tl = tablo_fiyat(
            gbp_px, "TL", self.fx.eur_try, self.fx.usd_try,
            sembol=sym, piyasa=piyasa, varlik_turu=varlik_turu,
            quote_currency="GBP" if sym.endswith(".L") else "",
            gbp_usd=self.fx.gbp_usd, eur_usd=self.fx.eur_usd,
        )
        usd = tablo_fiyat(
            gbp_px, "USD", self.fx.eur_try, self.fx.usd_try,
            sembol=sym, piyasa=piyasa, varlik_turu=varlik_turu,
            quote_currency="GBP" if sym.endswith(".L") else "",
            gbp_usd=self.fx.gbp_usd, eur_usd=self.fx.eur_usd,
        )
        assert_price_cross_consistency(
            gbp=gbp_px, usd=usd, tl=tl, fx=self.fx, label=sym,
        )
        return gbp_px, usd, tl

    def test_eqqq_jul15_usd_price_not_stale_127(self):
        gbp, usd, tl = self._columns("EQQQ.L")
        self.assertAlmostEqual(usd, gbp * self.fx.gbp_usd, delta=0.05)
        self.assertNotAlmostEqual(usd, gbp * 1.27, delta=1.0)
        self.assertAlmostEqual(usd, 714.65, delta=0.5)

    def test_eqqq_jul15_eur_fiyat_al_same_magnitude(self):
        """EUR çapraz: FİYAT ≈623.51, AL aynı mertebe — oran ~1.0 (100 DEĞİL)."""
        with open(META, encoding="utf-8") as f:
            golden = json.load(f)["golden"]["EQQQ.L"]
        settle = golden["spot_settlement"]
        al_settle = golden["al_price_settlement"]
        kw = dict(
            eur_try=self.fx.eur_try, usd_try=self.fx.usd_try,
            sembol="EQQQ.L", piyasa="ETF", varlik_turu="etf",
            quote_currency="GBP",
            gbp_usd=self.fx.gbp_usd, eur_usd=self.fx.eur_usd,
        )
        eur_fiyat = tablo_fiyat(settle, "EUR", **kw)
        eur_al = tablo_fiyat(al_settle, "EUR", **kw)
        beklenen_eur = eur_fiyat
        self.assertAlmostEqual(beklenen_eur, 625.24, delta=625.24 * 0.001)
        ratio = eur_fiyat / eur_al
        self.assertAlmostEqual(ratio, 1.0, delta=0.02)
        self.assertLess(ratio, 10.0, msg="100× GBp/GBP karışımı")

    def test_is3n_eur_cross_consistency_fixture(self):
        """EUR varlık — GBP üçlüsüyle aynı çapraz tutarlılık (fixture, CI deterministik)."""
        bars = BarSeries.from_df(self.df, "IS3N.DE")
        eur_px = float(bars.close.loc[:ASOF].iloc[-1])
        tl = tablo_fiyat(
            eur_px, "TL", self.fx.eur_try, self.fx.usd_try,
            sembol="IS3N.DE", piyasa="ETF", varlik_turu="etf",
            quote_currency="EUR", gbp_usd=self.fx.gbp_usd, eur_usd=self.fx.eur_usd,
        )
        usd = tablo_fiyat(
            eur_px, "USD", self.fx.eur_try, self.fx.usd_try,
            sembol="IS3N.DE", piyasa="ETF", varlik_turu="etf",
            quote_currency="EUR", gbp_usd=self.fx.gbp_usd, eur_usd=self.fx.eur_usd,
        )
        gbp_px = usd / self.fx.gbp_usd
        assert_price_cross_consistency(
            gbp=gbp_px, usd=usd, tl=tl, fx=self.fx, label="IS3N.DE",
        )
        self.assertAlmostEqual(usd, eur_px * self.fx.eur_usd, delta=0.05)
        self.assertAlmostEqual(tl, eur_px * self.fx.eur_try, delta=0.5)

    def test_eqqq_usd_1y_matches_gbp_fx(self):
        from signal_engine.data.bars import pct_change_calendar

        bars = BarSeries.from_df(self.df, "EQQQ.L")
        d1y = pct_change_calendar(bars.close, 365)
        usd_1y = tablo_getiri(
            d1y, "USD", 252, self.et, self.ut, gbp_seri=self.gbp,
            asset_pb="GBP", bar_dates=bars.close.index,
        )
        self.assertAlmostEqual(usd_1y, 26.8, delta=0.15)

    def test_wrong_start_481_is_april_not_1y(self):
        """481.26 = ~2026-04-21 (~3M); 1Y takvim başlangıç ≈ 2025-07-15."""
        from fiyat_para_fx import fx_window_dates_calendar

        bars = BarSeries.from_df(self.df, "EQQQ.L")
        close = bars.close.loc[:ASOF]
        wrong = float(close.loc[close.index.date.astype(str) == "2026-04-21"].iloc[0])
        d0, _ = fx_window_dates_calendar(close.index, 365)
        right = float(close.loc[d0])
        self.assertAlmostEqual(wrong, 481.26, delta=0.5)
        self.assertEqual(str(d0.date()), "2025-07-15")
        self.assertAlmostEqual(close.iloc[-1] / wrong - 1, 0.1084, places=3)
        self.assertGreater(close.iloc[-1] / right - 1, 0.20)

    @unittest.skipUnless(
        __import__("os").environ.get("FX_LIVE_CHECK"),
        "Canlı Yahoo — FX_LIVE_CHECK=1 ile çalıştır",
    )
    def test_emim_is3n_sxr8_live_jul15(self):
        syms = ["EMIM.L", "IS3N.DE", "SXR8.DE", "GBPUSD=X", "EURUSD=X", "USDTRY=X", "EURTRY=X"]
        df = _indir(syms, period="6mo")
        df = df.loc[:ASOF]
        snap, fx, et, ut, gbp = _snap_and_fx(df)
        for sym, qc in [("EMIM.L", "GBP"), ("IS3N.DE", "EUR"), ("SXR8.DE", "EUR")]:
            bars = BarSeries.from_df(df, sym)
            native = float(bars.close.iloc[-1])
            tl = tablo_fiyat(
                native, "TL", fx.eur_try, fx.usd_try, sembol=sym,
                quote_currency=qc, gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
            )
            usd = tablo_fiyat(
                native, "USD", fx.eur_try, fx.usd_try, sembol=sym,
                quote_currency=qc, gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
            )
            gbp_px = native if qc == "GBP" else usd / fx.gbp_usd
            assert_price_cross_consistency(
                gbp=gbp_px if qc == "GBP" else None,
                usd=usd, tl=tl, fx=fx, label=sym,
            )


if __name__ == "__main__":
    unittest.main()
