# -*- coding: utf-8 -*-
"""Bağımsız denetim düzeltmeleri — PPK/FOMC, SNAP GBP, atomik yazma."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import config


class PpkFomcCalendarTest(unittest.TestCase):
    def test_ppk_2026_official_tcmb(self):
        expected = [
            date(2026, 1, 22), date(2026, 3, 12), date(2026, 4, 22), date(2026, 6, 11),
            date(2026, 7, 23), date(2026, 9, 10), date(2026, 10, 22), date(2026, 12, 10),
        ]
        self.assertEqual(list(config.TCMB_PPK_TAKVIM), expected)

    def test_fomc_2026_official_fed(self):
        expected = [
            date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
            date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
        ]
        self.assertEqual(list(config.FOMC_TAKVIM), expected)

    def test_market_context_uses_config(self):
        import market_context as mc

        self.assertEqual(mc.TCMB_PPK_2026, list(config.TCMB_PPK_TAKVIM))
        self.assertEqual(mc.FOMC_2026, list(config.FOMC_TAKVIM))


class SnapFxFallbackTest(unittest.TestCase):
    def test_snap_fallback_no_invented_gbp(self):
        from fiyat_para import _fx_spot_snap_fallback

        snap = SimpleNamespace(
            veri=SimpleNamespace(eur_try=45.0, usd_try=41.0, eur_usd=45.0 / 41.0),
        )
        with patch("fiyat_para.kur_al", return_value=(45.0, 41.0)):
            fx = _fx_spot_snap_fallback(snap)
        self.assertIsNone(fx.gbp_usd)
        self.assertAlmostEqual(fx.eur_try, 45.0)
        self.assertAlmostEqual(fx.usd_try, 41.0)


class VarliklarimAtomicWriteTest(unittest.TestCase):
    def test_kaydet_store_atomic_replace(self):
        from varliklarim import VarlikStore, kaydet_store

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, ".varliklarim.json")
            store = VarlikStore()
            with patch("varliklarim.STATE_PATH", path):
                kaydet_store(store)
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("portfoyler", data)
            leftovers = [n for n in os.listdir(td) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
