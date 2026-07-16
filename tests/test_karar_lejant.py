# -*- coding: utf-8 -*-
"""Kozmetik: lejant, karar dağılımı, why percentile, Emir yok."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from karar_lejant import (
    TEFAS_YILDIZ_ACIKLAMA,
    karar_dagilim_ozeti,
    v2_lejant_markdown,
)
from signal_engine.decisions.state_machine import format_decision_why
from signal_engine.explain.why import why_markdown


class KararLejantTest(unittest.TestCase):
    def test_v2_lejant_bekle_degil_izle(self):
        md = v2_lejant_markdown()
        self.assertIn("GÜÇLÜ AL", md)
        self.assertIn("AZALT", md)
        self.assertIn("≠ İZLE", md)
        self.assertNotIn("BEKLE = izle", md.lower())

    def test_al_yildiz_aciklama(self):
        self.assertIn("AL*", TEFAS_YILDIZ_ACIKLAMA)
        self.assertIn("BEKLE*", TEFAS_YILDIZ_ACIKLAMA)
        self.assertIn("akran", TEFAS_YILDIZ_ACIKLAMA.lower())
        self.assertIn("BEKLE önerisi var ama akran grubu küçük", TEFAS_YILDIZ_ACIKLAMA)

    def test_karar_dagilim_dinamik(self):
        kararlar = (
            ["AL"] * 1
            + ["İZLE"] * 83
            + ["BEKLE"] * 11
            + ["AZALT"] * 9
        )
        ozet = karar_dagilim_ozeti(kararlar)
        self.assertEqual(ozet, "AL: 1 · İZLE: 83 · BEKLE: 11 · AZALT: 9")

    def test_pdf_baslik_karar_dagilimi(self):
        from report_pdf import hisse_etf_tablo_pdf_olustur

        df = pd.DataFrame({
            "Karar": ["AL", "İZLE", "İZLE", "BEKLE", "AZALT"],
            "Sembol": ["A", "B", "C", "D", "E"],
            "Emir": ["AL", "İZLE", "İZLE", "BEKLE", "AZALT"],  # atılmalı
        })
        pdf = hisse_etf_tablo_pdf_olustur(
            df, gosterim_pb="EUR",
            piyasa_filtre=["BIST"],
            sinyal_filtre=["Alım fırsatı", "Trend alımı", "Bekle"],
        )
        self.assertIsInstance(pdf, (bytes, bytearray))
        self.assertGreater(len(pdf), 100)
        # Emir sütunu PDF hazırlığında düşer
        from report_pdf import _df_pdf_hazirla
        cleaned = _df_pdf_hazirla(df)
        self.assertNotIn("Emir", cleaned.columns)

    def test_why_italic_uses_live_percentile(self):
        h = SimpleNamespace(
            sembol="AMAT",
            signal_v2_score=84.0,
            signal_v2_percentile=99.0,
            signal_v2_decision="AL",
            signal_v2_code="BUY",
            signal_v2_regime="TRENDING_UP",
            signal_v2_regime_detail="ADX yüksek",
            signal_v2_al_method="pullback",
            signal_v2_al_price=None,
            signal_v2_data="5/5",
            signal_v2_factors={"trend": 80.0},
            signal_v2_factor_details={"trend": "SMA ok"},
            signal_v2_decision_gates=[],
            signal_v2_prev_code="",
            signal_v2_hysteresis_note="",
            signal_v2_cold_start=False,
            signal_v2_cold_reason="",
            signal_v2_etf_quality="",
            signal_v2_why="Skor 84 (sınıf %50) · Rejim TRENDING_UP",  # eski/stale
        )
        md = why_markdown(h)
        self.assertIn("Sınıf içi:** %99", md)
        self.assertIn("sınıf %99", md)
        self.assertNotIn("sınıf %50", md)

    def test_format_decision_why_percentile(self):
        w = format_decision_why(72, 83.0, "RANGE", entry_method="spot")
        self.assertIn("sınıf %83", w)
        self.assertNotIn("%50", w)

    def test_v2_tablo_emir_yok(self):
        from portfoy_yoneticisi import yonetici_tablo_kolonlari
        from types import SimpleNamespace as SN

        h = SN(
            signal_v2_decision="İZLE",
            signal_v2_regime="RANGE",
            signal_v2_regime_detail="",
            signal_v2_regime_days=3,
            signal_v2_regime_fresh=False,
            signal_v2_code="WATCH",
            signal_v2_al_price=None,
            signal_v2_score=55.0,
            fiyat=10.0,
            sembol="TEST",
            piyasa="NASDAQ",
            quote_currency="USD",
            veri_quarantine=False,
            veri_hatasi="",
        )
        fx = SN(eur_try=50.0, usd_try=40.0, gbp_usd=1.3, eur_usd=1.1)
        kol = yonetici_tablo_kolonlari(h, "EUR", fx)
        self.assertNotIn("Emir", kol)
        self.assertIn("Al", kol)


if __name__ == "__main__":
    unittest.main()
