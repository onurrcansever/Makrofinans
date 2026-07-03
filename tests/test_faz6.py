# -*- coding: utf-8 -*-
"""Faz 6 — rapor ISIN birleştirme ve tekrar azaltma."""
import unittest
from types import SimpleNamespace

from report_pdf import _isin_birlestir_gosterim, _kotasyon_notu, _madde_ek_bilgi


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


if __name__ == "__main__":
    unittest.main()
