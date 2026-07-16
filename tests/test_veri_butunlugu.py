# -*- coding: utf-8 -*-
"""Veri bütünlüğü — tarama özeti + CSPX/VUAA takvim d0."""
from __future__ import annotations

import pickle
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from fiyat_para_fx import fx_window_dates, fx_window_dates_calendar
from signal_engine.data.bars import BarSeries
from veri_butunlugu import ozetle_hisseler, bar_sayisi_fark_uyarilari, tarama_butunluk_ozeti

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"


class VeriButunluguOzetTest(unittest.TestCase):
    def test_veri_butunlugu_ozet(self):
        hisseler = [
            SimpleNamespace(
                sembol="AMAT", sinyal="BEKLE", fiyat=100.0,
                veri_quarantine=False, close_bar_dates=pd.date_range("2025-01-01", periods=100, freq="B"),
                piyasa="NASDAQ",
            ),
            SimpleNamespace(
                sembol="FROTO.IS", sinyal="VERI_YOK", fiyat=None,
                veri_quarantine=False, close_bar_dates=None, piyasa="BIST",
            ),
            SimpleNamespace(
                sembol="X.L", sinyal="BEKLE", fiyat=10.0,
                veri_quarantine=True, close_bar_dates=pd.date_range("2025-01-01", periods=50, freq="B"),
                piyasa="ETF",
            ),
        ]
        o = ozetle_hisseler(hisseler)
        self.assertEqual(o.islenen, 3)
        self.assertEqual(o.veri_yok, ["FROTO.IS"])
        self.assertEqual(o.karantina, ["X.L"])
        self.assertIn("3 sembol işlendi", o.log_satiri)
        self.assertIn("1 veri yok", o.log_satiri)
        self.assertIn("FROTO.IS", o.log_satiri)
        self.assertIn("1 karantina", o.log_satiri)
        ui = o.ui_satiri
        self.assertIsNotNone(ui)
        self.assertIn("veri yok", ui)
        self.assertIn("karantina", ui)

    def test_bar_fark_warn_threshold(self):
        # 1 bar fark → uyarı yok; 3+ → var
        idx_a = pd.date_range("2025-01-01", periods=504, freq="B")
        idx_b = pd.date_range("2025-01-01", periods=505, freq="B")
        idx_c = pd.date_range("2025-01-01", periods=510, freq="B")
        hisseler_ok = [
            SimpleNamespace(
                sembol="CSPX.L", sinyal="BEKLE", fiyat=1.0,
                veri_quarantine=False, close_bar_dates=idx_a, piyasa="ETF",
            ),
            SimpleNamespace(
                sembol="VUAA.L", sinyal="BEKLE", fiyat=1.0,
                veri_quarantine=False, close_bar_dates=idx_b, piyasa="ETF",
            ),
        ]
        self.assertEqual(bar_sayisi_fark_uyarilari(hisseler_ok), [])

        hisseler_warn = [
            SimpleNamespace(
                sembol="CSPX.L", sinyal="BEKLE", fiyat=1.0,
                veri_quarantine=False, close_bar_dates=idx_a, piyasa="ETF",
            ),
            SimpleNamespace(
                sembol="VUAA.L", sinyal="BEKLE", fiyat=1.0,
                veri_quarantine=False, close_bar_dates=idx_c, piyasa="ETF",
            ),
        ]
        warns = bar_sayisi_fark_uyarilari(hisseler_warn)
        self.assertEqual(len(warns), 1)
        self.assertIn("LSE", warns[0])
        self.assertIn("6 bar fark", warns[0])


class CspxVuaaD0Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIX.open("rb") as f:
            cls.df = pickle.load(f)["df"]

    def test_cspx_vuaa_d0_esit(self):
        """Takvim 365g — CSPX/VUAA d0 aynı (±1 gün)."""
        cspx = BarSeries.from_df(self.df, "CSPX.L")
        vuaa = BarSeries.from_df(self.df, "VUAA.L")
        self.assertGreater(cspx.bars, 250)
        self.assertGreater(vuaa.bars, 250)

        d0_c, d1_c = fx_window_dates(cspx.close.index, 252)
        d0_v, d1_v = fx_window_dates(vuaa.close.index, 252)
        # Aynı d1 (fixture pin)
        self.assertEqual(d1_c.date(), d1_v.date())
        delta = abs((d0_c.normalize() - d0_v.normalize()).days)
        self.assertLessEqual(
            delta, 1,
            msg=f"CSPX d0={d0_c.date()} VUAA d0={d0_v.date()} (bar-ofset kayması olmamalı)",
        )
        # Eski bar-ofset yolu farklıydı (14 vs 15 Tem) — takvim bunu kapatır
        d0_bar_c = cspx.close.index[-253]
        d0_bar_v = vuaa.close.index[-253]
        if d0_bar_c.date() != d0_bar_v.date():
            # Takvim d0'ları bar-ofset farkına rağmen hizalı
            self.assertLessEqual(delta, 1)

    def test_1y_uses_calendar_not_252_bars(self):
        bars = BarSeries.from_df(self.df, "EQQQ.L")
        d0_cal, d1 = fx_window_dates_calendar(bars.close.index, 365)
        d0_bar = bars.close.index[-253]
        self.assertEqual(str(d1.date()), "2026-07-15")
        # Takvim d0 ≈ 2025-07-15 civarı; 252-bar ofset 2025-07-14
        self.assertAlmostEqual(
            (d1 - d0_cal).days, 365, delta=5,
        )
        self.assertNotEqual(d0_cal.date(), d0_bar.date())


if __name__ == "__main__":
    unittest.main()
