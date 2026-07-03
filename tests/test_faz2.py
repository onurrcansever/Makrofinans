# -*- coding: utf-8 -*-
"""Faz 2 — rejim kararlılığı testleri."""
import os
import tempfile
import unittest
from copy import deepcopy

import config
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot


def _snap(cds=240.0, vix=18.0, savas=0, siyasi=10, enflasyon=38.0):
    veri = PiyasaVerisi(
        eur_try=35.0,
        usd_try=32.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=cds,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=siyasi,
        savas_risk_makale_sayisi=savas,
        savas_risk_guvenilir=True,
    )
    return MacroSnapshot(
        veri=veri,
        vix=vix,
        enflasyon_tr_yillik=enflasyon,
        eur_usd=1.08,
    )


class Faz2RejimKararlilikTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "regime_state.json")
        self.onay = os.path.join(self.tmp, "girdi_onay.json")
        os.environ["REGIME_STATE_PATH"] = self.state
        os.environ["GIRDI_ONAY_STATE_PATH"] = self.onay
        config.REGIME_STATE_PATH = self.state
        config.GIRDI_ONAY_STATE_PATH = self.onay

    def test_profil_bagimsiz_rejim(self):
        from allocation_engine import tahsis_hesapla

        snap = _snap(cds=240, vix=18)
        p1 = YatirimProfili(risk="dusuk", vade="kisa")
        p2 = YatirimProfili(risk="yuksek", vade="uzun")
        r1 = tahsis_hesapla(snap, p1).rejim.rejim
        r2 = tahsis_hesapla(snap, p2).rejim.rejim
        self.assertEqual(r1, r2)

    def test_histerezis_iki_teyit(self):
        import json
        import regime_stability as rs

        rs.STATE_PATH = self.state
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"aktif_rejim": "NOTR"}, f)

        snap = _snap(cds=235, vix=14, savas=0, siyasi=75, enflasyon=29.0)
        from regime import rejim_tespit

        ham = rejim_tespit(snap)
        self.assertEqual(ham.rejim, "RISK_ON")

        r1 = rs.rejim_kararli_uygula(snap, None)
        self.assertEqual(r1.rejim, "NOTR")
        r2 = rs.rejim_kararli_uygula(snap, None)
        self.assertEqual(r2.rejim, "RISK_ON")
        self.assertTrue(r2.degisim_gerekce.startswith("Rejim"))

    def test_jeopolitik_risk_on_engeli(self):
        from regime import rejim_tespit

        snap = _snap(cds=240, vix=14, savas=config.SAVAS_RISK_ESIGI)
        ham = rejim_tespit(snap)
        self.assertNotEqual(ham.rejim, "RISK_ON")


if __name__ == "__main__":
    unittest.main()
