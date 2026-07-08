# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from enflasyon_kaynak import (
    _ay_fark_aylik,
    enflasyon_manuel_son,
    enflasyon_resmi_al,
)


class EnflasyonKaynakTest(unittest.TestCase):
    def test_ay_fark(self):
        self.assertEqual(_ay_fark_aylik("2026-6"), 1)  # July vs June

    def test_manuel_okuma(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manual_inputs.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "enflasyon_tr_yillik": 32.11,
                        "enflasyon_ay": "2026-6",
                        "enflasyon_guncelleme_notu": "TÜİK test",
                    },
                    f,
                )
            with patch("enflasyon_kaynak.MANUAL_PATH", path):
                son = enflasyon_manuel_son()
        self.assertIsNotNone(son)
        self.assertAlmostEqual(son[0], 32.11)
        self.assertEqual(son[2], "2026-6")

    @patch("enflasyon_kaynak.enflasyon_evds_son")
    @patch("enflasyon_kaynak.enflasyon_manuel_son")
    def test_manuel_evds_den_yeni_secilir(self, mock_man, mock_evds):
        mock_evds.return_value = (28.31, "EVDS 2025-12", "2025-12")
        mock_man.return_value = (32.11, "TÜİK Haziran", "2026-6")
        deger, kaynak, uyarilar = enflasyon_resmi_al("")
        self.assertAlmostEqual(deger, 32.11)
        self.assertIn("TÜİK", kaynak)
        self.assertEqual(uyarilar, [])


class BreakevenMetinTest(unittest.TestCase):
    def test_oran_alti_tl_lehine_metin(self):
        from rates_tr import _getiri_notu_metni

        metin = _getiri_notu_metni(4.0, 2.0, 53.5, 61.49)
        self.assertIn("1,0 altı", metin)
        self.assertIn("carry lehine", metin)
        self.assertNotIn("1.0 üzeri TL mevduat EUR mevduata göre avantajlı", metin)


if __name__ == "__main__":
    unittest.main()
