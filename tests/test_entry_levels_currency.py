# -*- coding: utf-8
"""Al seviyesi — settlement / gösterim para birimi tutarlılığı."""
from __future__ import annotations

import json
import pickle
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
import pandas as pd

from macro_data import MacroSnapshot
from decision_engine import PiyasaVerisi
from etf_universe import REVOLUT_ETFLER
from fiyat_para import tablo_fiyat
from portfoy_yoneticisi import _al_seviye_metni
from signal_engine.data.bars import BarSeries
from signal_engine.data.quote_normalize import convert_settlement
from signal_engine.config.loader import load_signal_config
from signal_engine.regime.classifier import classify_regime
from signal_engine.entry.levels import EntrySanityError, compute_entry, SPOT_NEAR_PCT
from signal_engine.pipeline import signal_engine_v2_uygula
from stock_scanner import _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
META = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"


def _load():
    with FIX.open("rb") as f:
        blob = pickle.load(f)
    with META.open(encoding="utf-8") as f:
        meta = json.load(f)
    return blob["df"], blob["snap"], meta["golden"]


class EntryLevelsCurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, cls.snap_vals, cls.golden = _load()
        cls.snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=cls.snap_vals["eur_try"],
            usd_try=cls.snap_vals["usd_try"],
        ))

    def test_eqqq_jul15_spot_near_by_distance(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        cfg = load_signal_config()
        regime = classify_regime(bars, cfg)
        entry = compute_entry(bars, regime.regime, cfg)
        exp = self.golden["EQQQ.L"]
        self.assertTrue(entry.spot_near)
        self.assertLessEqual(entry.spot_distance_pct or 999, SPOT_NEAR_PCT * 100 + 0.01)
        self.assertAlmostEqual(entry.price, exp["al_price_settlement"], places=2)

    def test_cross_currency_spot_triggers_sanity(self):
        close = pd.Series(np.r_[np.full(280, 500.0), np.full(20, 677.0)])
        bars = BarSeries.from_series(close, settlement_currency="USD")
        cfg = load_signal_config()
        from signal_engine.entry.levels import EntrySanityError
        with self.assertRaises(EntrySanityError):
            compute_entry(bars, "TRENDING_UP", cfg)

    def test_live_usd_spot_converted_to_gbp_settlement(self):
        t = next(x for x in REVOLUT_ETFLER if x[0] == "EQQQ.L")
        live = unittest.mock.Mock(
            price=677.47,
            settlement="USD",
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            age_min=1.0,
        )
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=live):
            h = _hisse_analiz(
                self.df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
                isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
            )
        from fiyat_para_fx import kur_tablo_spot
        from signal_engine.data.bars import _extract_close
        et = _extract_close(self.df, "EURTRY=X")
        ut = _extract_close(self.df, "USDTRY=X")
        gbp = _extract_close(self.df, "GBPUSD=X")
        eurusd = _extract_close(self.df, "EURUSD=X")
        fx = kur_tablo_spot(self.snap, et, ut, gbp, eurusd)
        gbp_from_usd = convert_settlement(
            677.47, "USD", "GBP",
            eur_try=fx.eur_try, usd_try=fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        self.assertEqual(h.quote_currency, "GBP")
        self.assertAlmostEqual(h.fiyat, gbp_from_usd, delta=1.0)

    def test_al_column_same_display_currency_as_spot(self):
        t = next(x for x in REVOLUT_ETFLER if x[0] == "EQQQ.L")
        h = _hisse_analiz(
            self.df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
            isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
        )
        from fiyat_para_fx import kur_tablo_spot
        from signal_engine.data.bars import _extract_close
        et = _extract_close(self.df, "EURTRY=X")
        ut = _extract_close(self.df, "USDTRY=X")
        gbp = _extract_close(self.df, "GBPUSD=X")
        eurusd = _extract_close(self.df, "EURUSD=X")
        fx = kur_tablo_spot(self.snap, et, ut, gbp, eurusd)
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula([h], self.df, profil_risk="orta")
        txt = _al_seviye_metni(h, "USD", fx)
        spot_usd = tablo_fiyat(
            h.fiyat, "USD", fx.eur_try, fx.usd_try,
            sembol=h.sembol, piyasa=h.piyasa, varlik_turu="etf",
            quote_currency=h.quote_currency,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        self.assertIn("spot civarı", txt)
        self.assertIsNotNone(spot_usd)
        self.assertIn("USD", txt)
        self.assertNotIn("523", txt.split("(")[0])


if __name__ == "__main__":
    unittest.main()
