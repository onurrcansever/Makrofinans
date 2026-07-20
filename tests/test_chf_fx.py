# -*- coding: utf-8 -*-
"""ADIM 1 — CHFUSD omurga + .SW→CHF + CHF→EUR smoke."""
from __future__ import annotations

import unittest

import pandas as pd

from fiyat_para_fx import assert_chf_eur_cross, kur_tablo_spot
from signal_engine.data.quote_normalize import convert_settlement, resolve_quote_currency


class ChfFxTest(unittest.TestCase):
    def test_sw_suffix_is_chf(self):
        self.assertEqual(resolve_quote_currency("NOVN.SW"), "CHF")
        self.assertEqual(resolve_quote_currency("NESN.SW"), "CHF")
        self.assertEqual(resolve_quote_currency("RO.SW"), "CHF")
        # EUR Avrupa sonekleri değişmedi
        self.assertEqual(resolve_quote_currency("ASML.AS"), "EUR")
        self.assertEqual(resolve_quote_currency("SAP.DE"), "EUR")
        self.assertEqual(resolve_quote_currency("AIR.PA"), "EUR")

    def test_chf_to_eur_smoke_novn(self):
        # Pin: ~18 Tem 2026 teşhis değerleri
        chf_usd = 1.2392
        eur_usd = 1.1450
        novn_chf = 125.0
        expected_eur = novn_chf * chf_usd / eur_usd
        got = convert_settlement(
            novn_chf, "CHF", "EUR",
            eur_try=53.0, usd_try=47.0,
            gbp_usd=1.34, eur_usd=eur_usd, chf_usd=chf_usd,
        )
        self.assertAlmostEqual(got, expected_eur, places=4)
        # Makul bant: 125 CHF ≈ 135 EUR civarı
        self.assertGreater(got, 120.0)
        self.assertLess(got, 150.0)

    def test_chf_eur_cross_within_0_1_pct(self):
        # CHFUSD / EURUSD ≈ CHFEUR
        chf_usd = 1.2392
        eur_usd = 1.1450
        chf_eur = chf_usd / eur_usd  # tam tutarlı
        assert_chf_eur_cross(chf_usd, eur_usd, chf_eur, tol_pct=0.1)
        # %0.1 içinde sapma kabul
        assert_chf_eur_cross(chf_usd, eur_usd, chf_eur * 1.0005, tol_pct=0.1)
        with self.assertRaises(Exception):
            assert_chf_eur_cross(chf_usd, eur_usd, chf_eur * 1.002, tol_pct=0.1)

    def test_kur_tablo_spot_requires_chf(self):
        idx = pd.date_range("2026-07-01", periods=5, freq="B")
        eur = pd.Series(53.0, index=idx)
        usd = pd.Series(47.0, index=idx)
        gbp = pd.Series(1.34, index=idx)
        eurusd = pd.Series(53.0 / 47.0, index=idx)
        with self.assertRaises(Exception):
            kur_tablo_spot(None, eur, usd, gbp, eurusd)
        chf = pd.Series(1.24, index=idx)
        fx = kur_tablo_spot(None, eur, usd, gbp, eurusd, chf_s=chf, check_plausibility=False)
        self.assertAlmostEqual(fx.chf_usd, 1.24, places=4)

    def test_golden_fixture_chf_pinned_and_cross(self):
        """ADIM 5 — fixture CHFUSD pin; CHFUSD/EURUSD ≈ CHFEUR (%0.1)."""
        import json
        import pickle
        from pathlib import Path

        from signal_engine.data.bars import _extract_close

        root = Path(__file__).resolve().parent / "fixtures"
        with (root / "signal_golden_20260715.pkl").open("rb") as f:
            payload = pickle.load(f)
        df = payload["df"]
        with (root / "signal_golden_20260715.json").open(encoding="utf-8") as f:
            meta = json.load(f)
        self.assertIn("chf_usd", meta["snap"])
        self.assertGreater(meta["snap"]["chf_usd"], 1.05)
        self.assertLess(meta["snap"]["chf_usd"], 1.40)
        chf = _extract_close(df, "CHFUSD=X")
        eu = _extract_close(df, "EURUSD=X")
        self.assertFalse(chf.empty)
        asof = pd.Timestamp("2026-07-15")
        chf_v = float(chf.loc[:asof].iloc[-1])
        eu_v = float(eu.loc[:asof].iloc[-1])
        # Pin ~1.24 band (15–18 Tem)
        self.assertAlmostEqual(chf_v, 1.24, delta=0.03)
        implied_chfeur = chf_v / eu_v
        # Sentetik CHFEUR = implied → çapraz %0
        assert_chf_eur_cross(chf_v, eu_v, implied_chfeur, tol_pct=0.1)


if __name__ == "__main__":
    unittest.main()
