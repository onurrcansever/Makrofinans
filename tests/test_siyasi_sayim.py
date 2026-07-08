# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock

from decision_engine import PiyasaVerisi
from macro_data import MacroSnapshot
from siyasi_etkin import siyasi_sayim_raporla


class SiyasiSayimTest(unittest.TestCase):
    def test_ozet_ve_kapi_ayni_sayim(self):
        snap = MacroSnapshot(
            veri=PiyasaVerisi(siyasi_risk_makale_sayisi=53),
            kaynak_haritasi={"siyasi_risk": "GDELT önbellek"},
        )
        sentiment = MagicMock()
        sentiment.siyasi.haber_sayisi = 53
        sentiment.etkin_siyasi = 32
        sentiment.kap1_siyasi = 32

        kap1 = siyasi_sayim_raporla(snap, sentiment)
        self.assertEqual(kap1, 32)
        self.assertEqual(snap.veri.siyasi_risk_makale_sayisi, 32)
        self.assertIn("Kapı 1 sayımı 32", snap.kaynak_haritasi["siyasi_risk"])
        self.assertIn("ham GDELT 53", snap.kaynak_haritasi["siyasi_risk"])


if __name__ == "__main__":
    unittest.main()
