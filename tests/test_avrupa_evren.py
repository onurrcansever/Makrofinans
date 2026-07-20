# -*- coding: utf-8 -*-
"""ADIM 4 — Avrupa / savunma-uzay evren smoke (fixture dışı semboller)."""
from __future__ import annotations

import unittest

from etf_universe import REVOLUT_ETFLER
from signal_engine.data.quote_normalize import convert_settlement, resolve_quote_currency
from stock_universe import (
    AVRUPA_HISSELER,
    SAVUNMA_UZAY,
    tum_evren,
    tum_etflar,
    tum_hisseler,
)


class AvrupaEvrenTest(unittest.TestCase):
    def test_tum_evren_128(self):
        # 110 + 14 Avrupa + 3 US savunma + 1 ITA ETF = 128
        self.assertEqual(len(tum_evren()), 128)

    def test_ro_sw_cs_pa_in_universe(self):
        syms = {r[0] for r in tum_evren()}
        self.assertIn("RO.SW", syms)
        self.assertIn("CS.PA", syms)
        self.assertNotIn("ROG.SW", syms)
        self.assertNotIn("AXA.PA", syms)

    def test_ita_is_etf_not_hisse(self):
        hisse_syms = {r[0] for r in tum_hisseler()}
        etf_syms = {r[0] for r in tum_etflar()}
        self.assertNotIn("ITA", hisse_syms)
        self.assertIn("ITA", etf_syms)
        self.assertTrue(any(s == "ITA" for s, *_ in REVOLUT_ETFLER))
        # SAVUNMA_UZAY listesinde ITA yok
        self.assertFalse(any(s == "ITA" for s, *_ in SAVUNMA_UZAY))

    def test_avrupa_count_and_piyasa(self):
        self.assertEqual(len(AVRUPA_HISSELER), 14)
        av = [r for r in tum_hisseler() if r[2] == "AVRUPA"]
        self.assertEqual(len(av), 14)

    def test_pa_de_eur_path_regression(self):
        self.assertEqual(resolve_quote_currency("AIR.PA"), "EUR")
        self.assertEqual(resolve_quote_currency("SAP.DE"), "EUR")
        self.assertEqual(resolve_quote_currency("ASML.AS"), "EUR")
        eur = convert_settlement(
            100.0, "EUR", "USD",
            eur_try=53.0, usd_try=47.0, gbp_usd=1.34, eur_usd=1.145, chf_usd=1.24,
        )
        self.assertAlmostEqual(eur, 100.0 * 1.145, places=4)

    def test_chf_swiss_convert_smoke(self):
        for sym, px in (("NOVN.SW", 125.0), ("NESN.SW", 85.55), ("RO.SW", 339.6)):
            self.assertEqual(resolve_quote_currency(sym), "CHF")
            eur = convert_settlement(
                px, "CHF", "EUR",
                eur_try=53.0, usd_try=47.0,
                gbp_usd=1.34, eur_usd=1.145, chf_usd=1.2392,
            )
            self.assertGreater(eur, 0)
            # CHF→EUR ≈ CHFUSD/EURUSD
            self.assertAlmostEqual(eur, px * 1.2392 / 1.145, places=3)


if __name__ == "__main__":
    unittest.main()
