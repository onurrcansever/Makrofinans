# -*- coding: utf-8 -*-
"""Enflasyona endeksli portföy çizgisi: TÜFE endeks serisi + reel ref hesabı."""
import math
import unittest
from unittest.mock import patch

from enflasyon_kaynak import (
    _sentetik_endeks,
    cpi_gun,
    cpi_gun_gunluk,
    enflasyon_ref_serisi,
    tufe_endeks_serisi,
)


class SentetikEndeksTest(unittest.TestCase):
    def test_pozitif_enflasyon_monoton_artan(self):
        with patch("enflasyon_kaynak.enflasyon_manuel_son", return_value=(32.11, "test", "2026-06")):
            seri = _sentetik_endeks("2026-01", "2026-12")
        self.assertEqual(len(seri), 12)
        degerler = [seri[k] for k in sorted(seri)]
        for onceki, sonraki in zip(degerler, degerler[1:]):
            self.assertGreater(sonraki, onceki)
        # 12 ay bileşik ≈ yıllık oran
        self.assertAlmostEqual(degerler[-1] / degerler[0], (1 + 32.11 / 100) ** (11 / 12), places=4)

    def test_veri_yoksa_bos(self):
        with patch("enflasyon_kaynak.enflasyon_manuel_son", return_value=None):
            self.assertEqual(_sentetik_endeks("2026-01", "2026-06"), {})


class TufeEndeksSerisiTest(unittest.TestCase):
    def test_yedek_yol_sentetik_uretir(self):
        # EVDS anahtarı/verisi yok → sentetik endeks, "yaklaşık" kaynak
        with patch("disk_onbellek.disk_getir_aninda", return_value=None), \
             patch("enflasyon_kaynak.enflasyon_manuel_son", return_value=(50.0, "test", "2026-06")):
            seri, kaynak = tufe_endeks_serisi("2026-01", "2026-06")
        self.assertTrue(seri)
        self.assertIn("yaklaşık", kaynak)

    def test_evds_verisi_varsa_kullanir(self):
        sahte = {"2026-01": 100.0, "2026-02": 104.0}
        with patch("disk_onbellek.disk_getir_aninda", return_value=sahte):
            seri, kaynak = tufe_endeks_serisi("2026-01", "2026-02")
        self.assertEqual(seri, sahte)
        self.assertIn("EVDS", kaynak)


class CpiGunTest(unittest.TestCase):
    seri = {"2026-01": 100.0, "2026-03": 110.0}

    def test_ay_eslesme(self):
        self.assertEqual(cpi_gun(self.seri, "2026-01-15"), 100.0)
        self.assertEqual(cpi_gun(self.seri, "2026-03-20"), 110.0)

    def test_ara_ay_onceki_kullanir(self):
        self.assertEqual(cpi_gun(self.seri, "2026-02-10"), 100.0)

    def test_seri_oncesi_en_erken(self):
        self.assertEqual(cpi_gun(self.seri, "2025-12-01"), 100.0)

    def test_bos_seri_none(self):
        self.assertIsNone(cpi_gun({}, "2026-01-01"))


class CpiGunGunlukTest(unittest.TestCase):
    def test_aylar_arasi_gunluk_artan(self):
        seri = {"2026-01": 100.0, "2026-02": 110.0}
        c1 = cpi_gun_gunluk(seri, "2026-01-01")
        c15 = cpi_gun_gunluk(seri, "2026-01-16")
        c31 = cpi_gun_gunluk(seri, "2026-02-01")
        self.assertAlmostEqual(c1, 100.0)
        self.assertAlmostEqual(c31, 110.0)
        self.assertGreater(c15, c1)
        self.assertLess(c15, c31)

    def test_son_ay_otesi_gunluk_uzatir(self):
        # Aylık endeks Haziran'da bitiyor; Temmuz günleri düz kalmamalı
        seri = {"2026-05": 100.0, "2026-06": 102.0}
        c_haz = cpi_gun_gunluk(seri, "2026-06-15")
        c_tem_bas = cpi_gun_gunluk(seri, "2026-07-01")
        c_tem_son = cpi_gun_gunluk(seri, "2026-07-20")
        self.assertGreater(c_tem_bas, c_haz)
        self.assertGreater(c_tem_son, c_tem_bas)

    def test_tek_ay_yillik_oranla_uzatir(self):
        seri = {"2026-06": 100.0}
        c0 = cpi_gun_gunluk(seri, "2026-07-01", yillik_oran=32.0)
        c1 = cpi_gun_gunluk(seri, "2026-07-31", yillik_oran=32.0)
        self.assertGreater(c1, c0)


class EnflasyonRefSerisiTest(unittest.TestCase):
    def test_sabit_endekste_ref_maliyete_esit(self):
        seri = {"2026-01": 100.0, "2026-02": 100.0, "2026-03": 100.0}
        tarihler = ["2026-01-15", "2026-02-15", "2026-03-15"]
        maliyetler = [1000.0, 1500.0, 1500.0]
        ref = enflasyon_ref_serisi(tarihler, maliyetler, seri)
        self.assertAlmostEqual(ref[0], 1000.0)
        self.assertAlmostEqual(ref[1], 1500.0)
        self.assertAlmostEqual(ref[2], 1500.0)

    def test_yuzde_yuz_enflasyon_katki_iki_katina(self):
        seri = {"2026-01": 100.0, "2027-01": 200.0}
        tarihler = ["2026-01-15", "2027-01-15"]
        maliyetler = [1000.0, 1000.0]
        ref = enflasyon_ref_serisi(tarihler, maliyetler, seri)
        self.assertAlmostEqual(ref[0], 1000.0)
        self.assertAlmostEqual(ref[1], 2000.0)

    def test_ilk_katkidan_once_nan(self):
        seri = {"2026-01": 100.0, "2026-02": 110.0}
        tarihler = ["2026-01-15", "2026-02-15"]
        maliyetler = [float("nan"), 1000.0]
        ref = enflasyon_ref_serisi(tarihler, maliyetler, seri)
        self.assertTrue(math.isnan(ref[0]))
        self.assertAlmostEqual(ref[1], 1000.0)


class PozisyonMaliyetSerisiTest(unittest.TestCase):
    def test_alim_tarihine_gore_kademe(self):
        from types import SimpleNamespace
        from varliklarim import pozisyon_maliyet_serisi
        pozlar = [
            SimpleNamespace(alim_tarihi="2026-07-02", _m=1_200_000.0),
            SimpleNamespace(alim_tarihi="2026-07-13", _m=240_000.0),
        ]
        tarihler = ["2026-07-10", "2026-07-12", "2026-07-13", "2026-07-23"]
        seri = pozisyon_maliyet_serisi(pozlar, tarihler, lambda p: p._m)
        self.assertEqual(seri[0], 1_200_000.0)  # sadece ilk katkı
        self.assertEqual(seri[1], 1_200_000.0)
        self.assertEqual(seri[2], 1_440_000.0)  # ikinci katkı eklendi
        self.assertEqual(seri[3], 1_440_000.0)

    def test_alim_tarihi_bos_ilk_gunden_sayilir(self):
        from types import SimpleNamespace
        from varliklarim import pozisyon_maliyet_serisi
        pozlar = [SimpleNamespace(alim_tarihi="", _m=500.0)]
        seri = pozisyon_maliyet_serisi(pozlar, ["2026-07-01", "2026-07-02"], lambda p: p._m)
        self.assertEqual(seri, [500.0, 500.0])

    def test_katki_yok_nan(self):
        import math
        from types import SimpleNamespace
        from varliklarim import pozisyon_maliyet_serisi
        pozlar = [SimpleNamespace(alim_tarihi="2026-07-20", _m=100.0)]
        seri = pozisyon_maliyet_serisi(pozlar, ["2026-07-10", "2026-07-25"], lambda p: p._m)
        self.assertTrue(math.isnan(seri[0]))
        self.assertEqual(seri[1], 100.0)


if __name__ == "__main__":
    unittest.main()
