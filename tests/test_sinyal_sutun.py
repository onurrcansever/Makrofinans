# -*- coding: utf-8 -*-
"""Sinyal sütunu — 🔼/⏸/🔽; analist yoksa motor eşikleri."""
from __future__ import annotations

import io
import unittest

import pandas as pd

import temel_veri as tv
from report_pdf import _df_pdf_hazirla, hisse_etf_tablo_pdf_olustur


class SinyalSutunTest(unittest.TestCase):
    def test_motor_only_eqqq_cspx(self):
        self.assertEqual(tv.sinyal_isaret(66, {"tur": "etf"}), "🔼")
        self.assertEqual(tv.sinyal_isaret(66, None), "🔼")
        self.assertEqual(tv.sinyal_isaret(64, {"tur": "etf"}), "⏸")
        self.assertEqual(tv.sinyal_isaret(40, {"tur": "etf"}), "🔽")
        # BIST / hisse — analist yok
        self.assertEqual(tv.sinyal_isaret(70, {"tur": "hisse", "analist": None}), "🔼")
        self.assertEqual(tv.sinyal_isaret(50, {"tur": "hisse"}), "⏸")

    def test_analist_bimas_msft_nflx(self):
        # BIMAS: skor 59, 💚+37% → 🔼
        self.assertEqual(
            tv.sinyal_isaret(59, {
                "tur": "hisse", "analist": "buy", "hedef_fark_pct": 37,
            }),
            "🔼",
        )
        # MSFT: skor 40, 💚+39% → ⏸ (motor kötü, analist iyi)
        self.assertEqual(
            tv.sinyal_isaret(40, {
                "tur": "hisse", "analist": "strong_buy", "hedef_fark_pct": 39,
            }),
            "⏸",
        )
        # NFLX: skor 40, 🟡+10% → 🔽
        self.assertEqual(
            tv.sinyal_isaret(40, {
                "tur": "hisse", "analist": "hold", "hedef_fark_pct": 10,
            }),
            "🔽",
        )
        # Hedef eşiği +15%: CSCO benzeri +18% → 🔼; +15% sınır altı → ⏸
        self.assertEqual(
            tv.sinyal_isaret(65, {
                "tur": "hisse", "analist": "buy", "hedef_fark_pct": 18,
            }),
            "🔼",
        )
        self.assertEqual(
            tv.sinyal_isaret(65, {
                "tur": "hisse", "analist": "buy", "hedef_fark_pct": 15,
            }),
            "⏸",
        )

    def test_tooltips_analist_vs_motor(self):
        self.assertIn("Şimdi ne yap?", tv.sinyal_tooltip("🔼", analist_var=True))
        self.assertIn("aksiyon", tv.sinyal_tooltip("⏸", analist_var=True).lower())
        self.assertIn("aksiyon", tv.sinyal_tooltip("🔽", analist_var=True).lower())
        self.assertIn("Şimdi ne yap?", tv.sinyal_tooltip("🔼", analist_var=False))
        self.assertIn("Nötr momentum", tv.sinyal_tooltip("⏸", analist_var=False))
        self.assertIn("Zayıf momentum", tv.sinyal_tooltip("🔽", analist_var=False))

    def test_skor_label_no_triangle(self):
        label = tv.skor_label(65, 97, {
            "tur": "hisse", "analist": "buy",
            "analist_sayi": 14, "al_sayi": 14, "hedef_fark_pct": 37,
        })
        for mark in ("🔼", "⏸", "🔽"):
            self.assertNotIn(mark, label)

    def test_aksiyon_momentum_yan_yana(self):
        df = pd.DataFrame([
            {"⭐": "☆", "Şimdi ne yap?": "İZLE", "Momentum": "🔼", "Özet": "T:Nötr",
             "Rejim": "—", "Sembol": "EQQQ", "Hisse/ETF": "EQQQ", "Fiyat (EUR)": 1.0,
             "Alım seviyesi": "—", "Skor": "66 (92%)"},
            {"⭐": "☆", "Şimdi ne yap?": "İZLE", "Momentum": "⏸", "Özet": "T:Nötr",
             "Rejim": "—", "Sembol": "CSPX", "Hisse/ETF": "CSPX", "Fiyat (EUR)": 1.0,
             "Alım seviyesi": "—", "Skor": "64 (80%)"},
            {"⭐": "☆", "Şimdi ne yap?": "AZALT", "Momentum": "🔽", "Özet": "T:Zayıf",
             "Rejim": "—", "Sembol": "NFLX", "Hisse/ETF": "NFLX", "Fiyat (EUR)": 1.0,
             "Alım seviyesi": "—", "Skor": "40 (8%)"},
        ])
        data_cols = [c for c in df.columns if c != "⭐"]
        self.assertEqual(data_cols[:8], [
            "Şimdi ne yap?", "Momentum", "Özet", "Rejim", "Sembol", "Hisse/ETF",
            "Fiyat (EUR)", "Alım seviyesi",
        ])
        self.assertEqual(df.loc[df["Sembol"] == "EQQQ", "Momentum"].iloc[0], "🔼")
        self.assertEqual(df.loc[df["Sembol"] == "NFLX", "Momentum"].iloc[0], "🔽")

    def test_pdf_aksiyon_first_column(self):
        df = pd.DataFrame([
            {"⭐": "☆", "Şimdi ne yap?": "İZLE", "Momentum": "🔼", "Sembol": "EQQQ",
             "Skor": "66 (92%)"},
            {"⭐": "☆", "Şimdi ne yap?": "AZALT", "Momentum": "⏸", "Sembol": "MSFT",
             "Skor": "40 (7%) 💚53/55 +39%"},
            {"⭐": "☆", "Şimdi ne yap?": "AZALT", "Momentum": "🔽", "Sembol": "NFLX",
             "Skor": "40 (8%) 🟡12/40 +10%"},
        ])
        cleaned = _df_pdf_hazirla(df)
        self.assertEqual(list(cleaned.columns)[0], "Ne yap?")
        self.assertEqual(cleaned["Mom"].tolist(), ["↑", "=", "↓"])
        pdf = hisse_etf_tablo_pdf_olustur(df, gosterim_pb="EUR")
        self.assertTrue(pdf.startswith(b"%PDF"))
        from pypdf import PdfReader
        text = "\n".join(
            (p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages
        )
        self.assertLess(text.find("Ne yap"), text.find("Mom"))
        self.assertIn("↑", text)
        self.assertIn("=", text)
        self.assertIn("↓", text)


if __name__ == "__main__":
    unittest.main()
