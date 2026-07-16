# -*- coding: utf-8
"""Favoriler modülü testleri."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import favoriler as fav

META = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"


class FavorilerTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig = fav.STATE_PATH
        fav.STATE_PATH = os.path.join(self._tmpdir.name, "favoriler.json")

    def tearDown(self):
        fav.STATE_PATH = self._orig
        self._tmpdir.cleanup()

    def test_normalize_hisse_sembol(self):
        self.assertEqual(fav.normalize_sembol("hisse", "thyao"), "THYAO.IS")
        # ABD hisselerine .IS eklenmez
        self.assertEqual(fav.normalize_sembol("hisse", "AMAT"), "AMAT")
        self.assertEqual(fav.normalize_sembol("hisse", "CSCO"), "CSCO")
        self.assertEqual(fav.normalize_sembol("hisse", "UNH"), "UNH")
        # Yanlış kaydedilmiş AMAT.IS → AMAT
        self.assertEqual(fav.normalize_sembol("hisse", "AMAT.IS"), "AMAT")
        self.assertEqual(fav.normalize_sembol("hisse", "CSCO.IS"), "CSCO")

    def test_ekle_ve_duplicate(self):
        store = fav.FavoriStore()
        self.assertTrue(fav.favori_ekle(store, "hisse", "THYAO", ad="THY"))
        self.assertFalse(fav.favori_ekle(store, "hisse", "thyao.is"))
        self.assertEqual(len(store.items), 1)

    def test_persist(self):
        store = fav.FavoriStore()
        fav.favori_ekle(store, "etf", "VUSA.L", ad="Vanguard S&P")
        fav.favori_ekle(store, "tefas", "YLR", ad="Para Piyasası")
        yuklenen = fav.yukle_store()
        self.assertEqual(len(yuklenen.items), 2)
        self.assertTrue(fav.favori_var(yuklenen, "tefas", "YLR"))

    def test_toplu_ekle(self):
        store = fav.FavoriStore()
        n = fav.favori_toplu_ekle(
            store,
            [("hisse", "ASELS", "Aselsan"), ("hisse", "ASELS", "Dup"), ("etf", "CSPX.L", "CSPX")],
        )
        self.assertEqual(n, 2)
        self.assertEqual(len(store.items), 2)

    def test_toggle(self):
        store = fav.FavoriStore()
        self.assertTrue(fav.favori_toggle(store, "hisse", "THYAO"))
        self.assertTrue(fav.favori_var(store, "hisse", "THYAO.IS"))
        self.assertFalse(fav.favori_toggle(store, "hisse", "THYAO"))
        self.assertFalse(fav.favori_var(store, "hisse", "THYAO.IS"))

    def test_etf_canonical_eqqq(self):
        self.assertEqual(fav.normalize_sembol("etf", "EQQQ"), "EQQQ.L")
        self.assertEqual(fav.favori_anahtar("etf", "EQQQ"), ("etf", "EQQQ.L"))

    def test_kaydet_atomic_tmp_replace(self):
        store = fav.FavoriStore()
        fav.favori_ekle(store, "tefas", "YLR", ad="YLR")
        self.assertTrue(os.path.isfile(fav.STATE_PATH))
        # tmp artığı kalmamalı
        leftovers = [
            n for n in os.listdir(os.path.dirname(fav.STATE_PATH))
            if n.startswith(".favoriler.") and n.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_rapid_toggle_consistent(self):
        store = fav.FavoriStore()
        for _ in range(5):
            fav.favori_toggle(store, "tefas", "YLR", ad="YLR")
        # 5 toggle → tek sayı → favoride
        self.assertTrue(fav.favori_var(fav.yukle_store(), "tefas", "YLR"))

    def test_star_value_lock(self):
        import pandas as pd

        df = pd.DataFrame([
            {"⭐": "☆", "tur": "tefas", "sembol": "YLR", "fiyat": "1.96"},
            {"⭐": "★", "tur": "etf", "sembol": "EQQQ.L", "fiyat": "625.24"},
        ])
        once = fav.data_column_lock(df)
        data = df.drop(columns=["⭐"])
        sonra = fav.data_column_lock(data)
        self.assertEqual(once, sonra)

    def test_eqqq_settlement_fiyat_eur_not_100x(self):
        """533.44 GBP settlement → fixture zinciri EUR; quote_currency yokken patlar."""
        import pickle

        from fiyat_para import tablo_fiyat
        from fiyat_para_fx import kur_tablo_spot
        from signal_engine.data.bars import _extract_close
        from signal_engine.data.quote_normalize import MissingQuoteCurrencyError
        from decision_engine import PiyasaVerisi
        from macro_data import MacroSnapshot
        import pandas as pd

        with META.open(encoding="utf-8") as f:
            meta = json.load(f)
        snap_vals = meta["snap"]
        eq = meta["golden"]["EQQQ.L"]
        settle_gbp = eq["spot_settlement"]
        self.assertAlmostEqual(settle_gbp, 533.44, places=2)

        fix = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
        with fix.open("rb") as f:
            df = pickle.load(f)["df"]
        asof = pd.Timestamp("2026-07-15")
        snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=snap_vals["eur_try"], usd_try=snap_vals["usd_try"],
        ))
        fx = kur_tablo_spot(
            snap,
            _extract_close(df, "EURTRY=X"),
            _extract_close(df, "USDTRY=X"),
            _extract_close(df, "GBPUSD=X"),
            _extract_close(df, "EURUSD=X"),
            asof=asof,
        )
        kw = dict(
            eur_try=fx.eur_try, usd_try=fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        with_qc = tablo_fiyat(
            settle_gbp, "EUR", sembol="EQQQ.L", quote_currency="GBP", **kw,
        )
        beklenen_eur = 625.24
        self.assertAlmostEqual(with_qc, beklenen_eur, delta=beklenen_eur * 0.001)
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(settle_gbp, "EUR", sembol="EQQQ.L", **kw)
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(settle_gbp, "EUR", sembol="EQQQ.L", **kw)

    def test_scanner_eqqq_h_fiyat_is_settlement_gbp(self):
        """Scanner h.fiyat golden spot_settlement ile aynı mertebede (533.44 GBP)."""
        import pickle

        from decision_engine import PiyasaVerisi
        from macro_data import MacroSnapshot
        from stock_scanner import _hisse_analiz

        fix = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
        with fix.open("rb") as f:
            df = pickle.load(f)["df"]
        with META.open(encoding="utf-8") as f:
            meta = json.load(f)
        snap_vals = meta["snap"]
        exp = meta["golden"]["EQQQ.L"]["spot_settlement"]
        snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=snap_vals["eur_try"], usd_try=snap_vals["usd_try"],
        ))
        h = _hisse_analiz(
            df, "EQQQ.L", "EQQQ", "ETF", "teknoloji", "NOTR", snap, varlik_turu="etf",
        )
        self.assertIsNotNone(h.fiyat, msg="h.fiyat boş")
        ratio = max(h.fiyat, exp) / min(h.fiyat, exp)
        self.assertLess(
            ratio, 1.05,
            msg=(
                f"h.fiyat={h.fiyat} vs golden settlement={exp} — "
                "scanner/fixture çift değer bug'ı olabilir"
            ),
        )


if __name__ == "__main__":
    unittest.main()
