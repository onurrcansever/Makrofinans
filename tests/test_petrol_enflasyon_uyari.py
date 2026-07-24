# -*- coding: utf-8 -*-
"""petrol_enflasyon_uyari — danışman katmanı (karar motorunu değiştirmez)."""
from __future__ import annotations

import unittest

from petrol_enflasyon_uyari import petrol_enflasyon_uyarisi


class PetrolEnflasyonUyariTest(unittest.TestCase):
    def test_veri_yok(self):
        self.assertIsNone(petrol_enflasyon_uyarisi(None))
        self.assertIsNone(petrol_enflasyon_uyarisi("abc"))

    def test_dusuk_risk_uyari_yok(self):
        self.assertIsNone(petrol_enflasyon_uyarisi(5.0))
        self.assertIsNone(petrol_enflasyon_uyarisi(7.9))

    def test_izle_bandi(self):
        u = petrol_enflasyon_uyarisi(10.0)
        self.assertIsNotNone(u)
        self.assertEqual(u["seviye"], "izle")
        self.assertIn("Brent", u["mesaj"])
        self.assertIn("karar motoruna dahil değil", u["mesaj"])

    def test_yuksek_bandi(self):
        u = petrol_enflasyon_uyarisi(20.0)
        self.assertIsNotNone(u)
        self.assertEqual(u["seviye"], "yüksek")
        self.assertIn("İthal enflasyon", u["mesaj"])


if __name__ == "__main__":
    unittest.main()
