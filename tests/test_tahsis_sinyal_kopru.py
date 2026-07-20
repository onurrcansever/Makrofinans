# -*- coding: utf-8 -*-
"""Tahsis ↔ tarama AL köprüsü — BIST ince ayar (risk artırmaz)."""
import unittest
from types import SimpleNamespace as SN

from allocation_engine import (
    TahsisSonucu,
    al_aday_sayisi,
    tahsis_bist_sinyal_ayarla,
)
from regime import RejimSonucu


def _sonuc(bist=0.10, rejim="RISK_ON"):
    a = {
        "eur_cash": 0.40,
        "usd_cash": 0.20,
        "tl_deposit": 0.10,
        "gold": 0.20,
        "silver": 0.0,
        "bist": bist,
        "crypto": 0.0,
    }
    t = sum(a.values())
    a = {k: v / t for k, v in a.items()}
    return TahsisSonucu(
        agirliklar=dict(a),
        skorlar={},
        rejim=RejimSonucu(rejim=rejim, etiket=rejim, aciklama="", guven=0.8),
        tl_karar_adimlari=[],
        tl_tavan_oran=0.2,
        adimlar=["makro adım"],
        agirliklar_makro=dict(a),
    )


class AlAdaySayisiTest(unittest.TestCase):
    def test_buy_sayar(self):
        hs = [
            SN(signal_v2_code="BUY", veri_quarantine=False),
            SN(signal_v2_code="STRONG_BUY", veri_quarantine=False),
            SN(signal_v2_code="WATCH", veri_quarantine=False),
            SN(signal_v2_code="BUY", veri_quarantine=True),
        ]
        self.assertEqual(al_aday_sayisi(hs), 2)


class BistSinyalAyarTest(unittest.TestCase):
    def test_al_yok_kisir(self):
        s = _sonuc(bist=0.10)
        deg = tahsis_bist_sinyal_ayarla(s, 0)
        self.assertTrue(deg)
        self.assertAlmostEqual(s.agirliklar["bist"], 0.04, places=4)
        self.assertIn("AL yok", s.bist_sinyal_notu)
        self.assertTrue(any("Sinyal köprüsü" in x for x in s.adimlar))

    def test_al_var_korunur_artmaz(self):
        s = _sonuc(bist=0.10)
        makro = s.agirliklar_makro["bist"]
        deg = tahsis_bist_sinyal_ayarla(s, 3)
        self.assertTrue(deg)  # notu değişir
        self.assertAlmostEqual(s.agirliklar["bist"], makro, places=5)
        self.assertLessEqual(s.agirliklar["bist"], makro + 1e-9)
        self.assertIn("korundu", s.bist_sinyal_notu)

    def test_idempotent(self):
        s = _sonuc(bist=0.10)
        tahsis_bist_sinyal_ayarla(s, 0)
        b1 = s.agirliklar["bist"]
        tahsis_bist_sinyal_ayarla(s, 0)
        self.assertAlmostEqual(s.agirliklar["bist"], b1, places=6)
        self.assertEqual(sum(1 for x in s.adimlar if "Sinyal köprüsü" in x), 1)

    def test_kriz_dokunulmaz(self):
        s = _sonuc(bist=0.0, rejim="KRIZ")
        s.agirliklar["bist"] = 0.0
        s.agirliklar_makro["bist"] = 0.0
        tahsis_bist_sinyal_ayarla(s, 0)
        self.assertAlmostEqual(s.agirliklar["bist"], 0.0, places=6)
        self.assertIn("defansif", s.bist_sinyal_notu)

    def test_dusuk_bist_yariya_iner(self):
        s = _sonuc(bist=0.02)
        makro = s.agirliklar_makro["bist"]
        tahsis_bist_sinyal_ayarla(s, 0)
        self.assertAlmostEqual(s.agirliklar["bist"], makro * 0.5, places=4)
        self.assertLessEqual(s.agirliklar["bist"], 0.04 + 1e-9)


if __name__ == "__main__":
    unittest.main()
