# -*- coding: utf-8 -*-
"""Spot emtia (GC=F / SI=F) — evren, gram TL, motor sinyal, pipeline rel nötr."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from emtia_universe import (
    EMTIA_SEMBOLLER,
    gram_tl_from_oz,
    gram_tl_metin,
    tum_emtalar,
)
from stock_universe import tum_evren
from temel_veri import sinyal_isaret, sinyal_isaret_hisse


class EmtiaUniverseTest(unittest.TestCase):
    def test_emtia_in_tum_evren(self):
        ev = tum_evren()
        sem = {s for s, *_ in ev}
        self.assertIn("GC=F", sem)
        self.assertIn("SI=F", sem)
        emtia = [x for x in ev if x[2] == "EMTIA"]
        self.assertEqual(len(emtia), len(EMTIA_SEMBOLLER))
        self.assertEqual(len(tum_emtalar()), 2)

    def test_gram_tl_formula(self):
        # 3985 $/oz · USDTRY 47.10 → ~6034 TL/gram
        g = gram_tl_from_oz(3985.0, 47.10, ons_gram=31.1035)
        self.assertAlmostEqual(g, 6034.0, delta=2.0)
        txt = gram_tl_metin(3985.0, 47.10)
        self.assertTrue(txt.startswith("Gram: ~"))
        self.assertIn("TL/g", txt)
        # Binlik nokta belirsizliği yok (6.034 gibi görünmesin)
        self.assertNotIn("6.034", txt)
        self.assertIn("6034", txt.replace(" ", ""))

    def test_indir_tz_naive_concat(self):
        """Batch naive + Ticker.history UTC-aware birleşmeli."""
        from unittest.mock import patch
        import pandas as pd
        from stock_scanner import _indir, _df_sembol_var

        idx_naive = pd.bdate_range("2025-01-01", periods=40)
        idx_aware = pd.bdate_range("2025-01-01", periods=40, tz="UTC")
        close_n = pd.Series(range(100, 140), index=idx_naive, dtype=float)
        close_a = pd.Series(range(3900, 3940), index=idx_aware, dtype=float)

        batch = pd.DataFrame({
            ("AAPL", "Open"): close_n,
            ("AAPL", "High"): close_n,
            ("AAPL", "Low"): close_n,
            ("AAPL", "Close"): close_n,
            ("AAPL", "Volume"): 1.0,
        })
        batch.columns = pd.MultiIndex.from_tuples(batch.columns)

        with patch("yfinance.download", return_value=batch):
            with patch("yfinance.Ticker") as T:
                class _Tk:
                    def history(self, **kw):
                        return pd.DataFrame({
                            "Open": close_a, "High": close_a, "Low": close_a,
                            "Close": close_a, "Volume": 1.0,
                        }, index=idx_aware)
                T.side_effect = lambda s: _Tk()
                # AAPL batch'te var; GC=F eksik → tek ticker path
                out = _indir(["AAPL", "GC=F"], period="1y", timeout=5)
        self.assertTrue(_df_sembol_var(out, "AAPL"))
        self.assertTrue(_df_sembol_var(out, "GC=F"))
        self.assertIsNone(getattr(out.index, "tz", "x"))

    def test_motor_sinyal_thresholds(self):
        self.assertEqual(sinyal_isaret(67, {"tur": "emtia"}), "🔼")
        self.assertEqual(sinyal_isaret(66, {"tur": "emtia"}), "🔼")
        self.assertEqual(sinyal_isaret(65, {"tur": "emtia"}), "⏸")
        self.assertEqual(sinyal_isaret(41.9, {"tur": "emtia"}), "🔽")
        self.assertEqual(sinyal_isaret(42, {"tur": "emtia"}), "⏸")

    def test_sinyal_isaret_hisse_emtia(self):
        h = SimpleNamespace(
            sembol="GC=F",
            ad="Altın (ons)",
            piyasa="EMTIA",
            varlik_turu="emtia",
            skor=50,
            signal_v2_score=67.0,
            fiyat=3985.0,
        )
        self.assertEqual(sinyal_isaret_hisse(h), "🔼")
        h.signal_v2_score = 40.0
        self.assertEqual(sinyal_isaret_hisse(h), "🔽")


class EmtiaPipelineTest(unittest.TestCase):
    def _bars_df(self, sym: str, n: int = 120, seed: int = 1) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2024-01-02", periods=n, tz="UTC")
        close = 2000 + np.cumsum(rng.normal(0.2, 8, size=n))
        vol = rng.integers(50_000, 200_000, size=n).astype(float)
        cols = pd.MultiIndex.from_product([[sym], ["Open", "High", "Low", "Close", "Volume"]])
        data = np.column_stack([close, close * 1.01, close * 0.99, close, vol])
        # MultiIndex columns need wide layout: Open..Volume per ticker
        wide = {}
        for i, field in enumerate(["Open", "High", "Low", "Close", "Volume"]):
            wide[(sym, field)] = data[:, i]
        return pd.DataFrame(wide, index=idx)

    def test_pipeline_emtia_rel_neutral_and_score(self):
        from signal_engine.pipeline import signal_engine_v2_uygula
        from signal_engine.data.bars import asset_class_for, benchmark_symbol
        from signal_engine.config.loader import load_signal_config

        df = self._bars_df("GC=F", n=150)
        h = SimpleNamespace(
            sembol="GC=F",
            ad="Altın (ons)",
            piyasa="EMTIA",
            varlik_turu="emtia",
            sektor="altin",
            isin="",
            fiyat=float(df[("GC=F", "Close")].iloc[-1]),
            quote_currency="USD",
            skor=50.0,
            veri_quarantine=False,
            veri_hatasi="",
        )
        cfg = load_signal_config()
        self.assertEqual(asset_class_for(h, cfg), "emtia")
        self.assertEqual(benchmark_symbol(h, cfg), "")

        signal_engine_v2_uygula([h], df, profil_risk="orta", persist_decision_history=False)
        self.assertIsNotNone(h.signal_v2_score)
        self.assertEqual(h.signal_v2_factors.get("relative_strength"), 50.0)
        self.assertIn("nötr", (h.signal_v2_factor_details.get("relative_strength") or "").lower())
        self.assertTrue(h.signal_v2_decision)


class EmtiaBildirimTest(unittest.TestCase):
    def test_al_etiket_and_satir(self):
        from al_bildirim import al_etiket_kisa, emtia_sinyal_satiri, guncel_al_satirlar

        h = SimpleNamespace(
            sembol="GC=F",
            ad="Altın (ons)",
            piyasa="EMTIA",
            varlik_turu="emtia",
            skor=67,
            alim_uygun="UYGUN",
            fiyat=3985.0,
            signal_v2_decision="AL",
            signal_v2_score=67.0,
            signal_v2_percentile=80.0,
            rsi=50,
            sinyal="BEKLE",
        )
        et = al_etiket_kisa(h)
        self.assertIn("Altın", et)
        self.assertIn("3985", et.replace(",", ""))
        sat = emtia_sinyal_satiri(h)
        self.assertIn("sinyali", sat)
        self.assertTrue(sat.startswith("🔼") or "🔼" in sat)
        metin = "\n".join(guncel_al_satirlar([h]))
        self.assertIn("emtia", metin.lower())


if __name__ == "__main__":
    unittest.main()
