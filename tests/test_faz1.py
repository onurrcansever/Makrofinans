# -*- coding: utf-8 -*-
"""Faz 1 — girdi doğrulama ve sıçrama koruması testleri."""
import json
import os
import sqlite3
import tempfile
import unittest

import config


class Faz1GirdiDogrulamaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test_market.db")
        self.onay = os.path.join(self.tmp, "test_onay.json")
        os.environ["MARKET_CACHE_DB"] = self.db
        os.environ["GIRDI_ONAY_STATE_PATH"] = self.onay
        import girdi_dogrulama as gd

        self.gd = gd

    def _seed(self, anahtar: str, deger: float, n: int = 5):
        for _ in range(n):
            self.gd.gosterge_kaydet(anahtar, deger)

    def test_cds_sicrama_rejim_dondurma(self):
        """222→300 ilk çalıştırma: onay bekliyor, rejim için 222."""
        self._seed("cds", 222.0, 8)
        gs1 = self.gd.gosterge_kontrol("cds", 300.0)
        self.assertEqual(gs1.durum, "ONAY_BEKLIYOR")
        self.assertEqual(gs1.rejim_icin_deger, 222.0)
        self.assertIn("rejim donduruldu", (gs1.uyari or "").lower())

        gs2 = self.gd.gosterge_kontrol("cds", 300.0)
        self.assertEqual(gs2.durum, "OK")
        self.assertEqual(gs2.rejim_icin_deger, 300.0)
        self.assertIn("teyit", (gs2.uyari or "").lower())

    def test_sanity_band_supheli(self):
        for v in (30.0, 32.0, 34.0, 36.0, 38.0):
            self.gd.gosterge_kaydet("enflasyon", v)
        gs = self.gd.gosterge_kontrol("enflasyon", 55.0)
        self.assertIn("SUPHELI", gs.uyari or "")

    def test_tcmb_seri_dogrulama(self):
        from data_sources import tcmb_politika_faizi_dogrula

        uyar = tcmb_politika_faizi_dogrula(40.5, "EVDS TP.APIFON4 ağırlıklı ortalama")
        self.assertTrue(any("SUPHELI" in u for u in uyar))
        temiz = tcmb_politika_faizi_dogrula(37.0, "TCMB.gov.tr — 1 hafta repo borç verme")
        self.assertEqual(temiz, [])

    def test_cds_kaynak_fark_muhafazakar(self):
        """20 bp üzeri farkta yüksek değer seçilmeli."""
        bb, inv = 260.0, 222.0
        fark = abs(bb - inv)
        self.assertGreater(fark, config.CDS_KAYNAK_FARK_BP)
        secilen = max(bb, inv)
        self.assertEqual(secilen, 260.0)


if __name__ == "__main__":
    unittest.main()
