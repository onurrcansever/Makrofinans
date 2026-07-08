# -*- coding: utf-8 -*-
"""TEFAS fon modülü testleri."""
import unittest
from unittest.mock import patch

from investor_profile import YatirimProfili
from tefas_skor import fonlari_skorla, top_oneri
from tefas_universe import fon_kategorisi, fon_para_birimi, kisa_fon_adi, yk_fon_mu
from tefas_data import FonPerformans, TefasTaramaSonuc, _getiri_hesapla
import pandas as pd


class TefasUniverseTest(unittest.TestCase):
    def test_yk_tespit(self):
        self.assertTrue(yk_fon_mu("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"))
        self.assertFalse(yk_fon_mu("AK PORTFÖY"))

    def test_kategori_pp(self):
        ad = "YAPI KREDİ PORTFÖY PARA PİYASASI FONU"
        self.assertEqual(fon_kategorisi(ad), "para_piyasasi")

    def test_kisa_ad(self):
        self.assertIn("PARA", kisa_fon_adi("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"))

    def test_para_birimi(self):
        self.assertEqual(fon_para_birimi("SERBEST (DÖVİZ-AVRO) FON"), "EUR")


class TefasSkorTest(unittest.TestCase):
    def test_skor_sirala(self):
        f1 = FonPerformans(
            kod="YLB", ad="x", kisa_ad="PP", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_3a=5.0,
        )
        f2 = FonPerformans(
            kod="YHS", ad="y", kisa_ad="Hisse", kategori="hisse",
            kategori_etiket="Hisse", para_birimi="TL", para_etiket="TL",
            fiyat=25.0, getiri_3a=15.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[f1, f2]),
            YatirimProfili(risk="dusuk", vade="kisa_6"),
            rejim="TL_FIRSAT",
            mevduat_reel=2.0,
        )
        self.assertEqual(sonuc.fonlar[0].kod, "YLB")

    def test_kisa_3_degisken_geride(self):
        pp = FonPerformans(
            kod="PKT", ad="pp", kisa_ad="PP", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_1a=4.0,
        )
        deg = FonPerformans(
            kod="YAK", ad="y", kisa_ad="Deg", kategori="degisken",
            kategori_etiket="Deg", para_birimi="TL", para_etiket="TL",
            fiyat=10.0, getiri_1a=12.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[deg, pp]),
            YatirimProfili(risk="orta", vade="kisa_3"),
            rejim="TL_FIRSAT",
        )
        self.assertEqual(sonuc.fonlar[0].kod, "PKT")
        aday = top_oneri(sonuc, n=2, kategoriler=("para_piyasasi", "borclanma", "katilim"))
        self.assertTrue(aday)
        self.assertEqual(aday[0].kategori, "para_piyasasi")


class TefasGetiriTest(unittest.TestCase):
    def test_getiri_hesap(self):
        df = pd.DataFrame({
            "date_dt": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "price": [100.0, 105.0, 110.0],
        })
        g = _getiri_hesapla(df, 30)
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g, 10.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
