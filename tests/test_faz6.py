# -*- coding: utf-8 -*-
"""Faz 6 — rapor ISIN birleştirme ve tekrar azaltma."""
import unittest
from types import SimpleNamespace

import pandas as pd

from report_pdf import (
    _html_temiz,
    _isin_birlestir_gosterim,
    _kotasyon_notu,
    _madde_ek_bilgi,
    hisse_etf_tablo_pdf_olustur,
)


class Faz6RaporTest(unittest.TestCase):
    def test_isin_birlestir(self):
        h1 = SimpleNamespace(
            isin="IE00B4L5Y983", sembol="EMIM.L", ad="EMIM", skor=70,
            alim_uygun="UYGUN", sinyal="ALIM_FIRSATI", piyasa="ETF",
            revolut_ticker="EMIM", degisim_1ay=1.0, rsi=55,
            alim_uygun_not="", haber_notu="", rejim_notu="", profil_notu="",
        )
        h2 = SimpleNamespace(
            isin="IE00B4L5Y983", sembol="IS3N.DE", ad="IS3N", skor=68,
            alim_uygun="UYGUN", sinyal="ALIM_FIRSATI", piyasa="ETF",
            revolut_ticker="IS3N", degisim_1ay=1.0, rsi=54,
            alim_uygun_not="", haber_notu="", rejim_notu="", profil_notu="",
        )
        birlestir = _isin_birlestir_gosterim([h1, h2])
        self.assertEqual(len(birlestir), 1)
        self.assertIn("EMIM.L", birlestir[0]._kotasyonlar)
        self.assertIn("IS3N.DE", birlestir[0]._kotasyonlar)

    def test_madde_ek_bilgi_tablo_tekrarlamaz(self):
        h = SimpleNamespace(
            rsi=50, skor=60, ad="X", sembol="X", sinyal="BEKLE",
            degisim_1ay=0, degisim_3ay=0, zirve_52h_pct=90,
            alim_uygun_not="", trend_notu="Trend filtresi OK",
            haber_notu="", rejim_notu="", profil_notu="",
        )
        self.assertIsNone(_madde_ek_bilgi(h))
        h.haber_notu = "Olumsuz haber akışı"
        self.assertIn("Haber", _madde_ek_bilgi(h))

    def test_hisse_etf_tablo_pdf(self):
        df = pd.DataFrame([{
            "⭐": "☆",
            "Şimdi ne yap?": "İZLE",
            "Sembol": "AAPL",
            "Hisse/ETF": "Apple Inc.",
            "Fiyat (USD)": "198.50",
            "1G % (USD)": float("nan"),
            "Alım seviyesi": "spot civarı (198.50 USD) / 2: 190.00 USD",
            "Skor": "59 (73%) 💚14/14 +37%",
            "Rejim": '<span>↗ Trend ↑</span><div>1 gündür</div>',
            "Veri": "4/5 · 1 sa",
            "90g": [1, 2, 3],
        }])
        pdf = hisse_etf_tablo_pdf_olustur(
            df,
            gosterim_pb="USD",
            piyasa_filtre=["NASDAQ"],
            sinyal_filtre=["Bekle"],
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn(b"<span>", pdf)
        from report_pdf import _df_pdf_hazirla
        cleaned = _df_pdf_hazirla(df)
        self.assertEqual(cleaned["Skor"].iloc[0], "59 (73%) AL14/14 +37%")
        self.assertEqual(cleaned["Rejim"].iloc[0], "Trend ↑")
        self.assertEqual(cleaned["Al sev."].iloc[0], "≈(198.50 USD)")
        self.assertEqual(cleaned["1G % (USD)"].iloc[0], "—")
        self.assertNotIn("Veri", cleaned.columns)
        # PDF metninde analist sayısı + hedef fark
        import io
        from pypdf import PdfReader
        text = "\n".join(
            (p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages
        )
        self.assertIn("14/14", text)
        self.assertIn("+37%", text)
        self.assertIn("AL14/14", text)
        self.assertNotIn("gündür", text)
        self.assertNotIn("4/5", text)

    def test_html_temiz(self):
        self.assertEqual(_html_temiz('<b>Trend +</b>'), "Trend +")


if __name__ == "__main__":
    unittest.main()
