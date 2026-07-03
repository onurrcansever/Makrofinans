# -*- coding: utf-8 -*-
"""Vade sonu net tutar — portföy dilimi vs manuel tutar şeffaflığı."""
import unittest

from rates_tr import tl_vade_sonu_hesapla, tl_vade_sonu_rapor_metni


class VadeSonuTutarTest(unittest.TestCase):
    def test_portfoy_dilimi_32k_ornek(self):
        """30.000 EUR × %2 × 53,62 ≈ 32.173 TL — tam portföy değil."""
        ozet = tl_vade_sonu_hesapla(
            toplam_eur=30_000,
            tl_agirlik=0.02,
            eur_try=53.62,
            brut_yillik=0.42,
            gun=93,
        )
        self.assertIsNotNone(ozet)
        self.assertEqual(ozet.taban, "portfoy_dilimi")
        self.assertAlmostEqual(ozet.anapara_tl, 30_000 * 0.02 * 53.62, delta=1)
        metin = tl_vade_sonu_rapor_metni(ozet)
        self.assertIn("TL mevduat dilimi", metin)
        self.assertIn("tamamı değil", metin)
        self.assertNotIn("anapara ~", metin)

    def test_manuel_1_2m_mevduat(self):
        ozet = tl_vade_sonu_hesapla(
            toplam_eur=30_000,
            tl_agirlik=0.02,
            eur_try=53.62,
            brut_yillik=0.42,
            gun=93,
            manuel_anapara_tl=1_200_000,
        )
        self.assertEqual(ozet.taban, "manuel")
        self.assertAlmostEqual(ozet.anapara_tl, 1_200_000)
        self.assertAlmostEqual(ozet.brut_faiz, 1_200_000 * 0.42 * 93 / 365, delta=5000)
        self.assertAlmostEqual(ozet.stopaj_tutar, ozet.brut_faiz * 0.15, delta=1000)
        self.assertGreater(ozet.net_tl, 1_300_000)
        metin = tl_vade_sonu_rapor_metni(ozet)
        self.assertIn("girdiğiniz mevduat tutarı", metin)


if __name__ == "__main__":
    unittest.main()
