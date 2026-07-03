# -*- coding: utf-8 -*-
"""Faz 3 — senaryo analizi testleri."""
import unittest

import config
from allocation_engine import tahsis_hesapla
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from scenario_analysis import senaryo_analizi_uret


def _snap():
    veri = PiyasaVerisi(
        eur_try=35.0,
        usd_try=32.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=222.0,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=10,
        savas_risk_makale_sayisi=0,
        savas_risk_guvenilir=True,
    )
    return MacroSnapshot(veri=veri, vix=18.0, enflasyon_tr_yillik=35.0, eur_usd=1.08)


class Faz3SenaryoTest(unittest.TestCase):
    def test_uc_senaryo_uretilir(self):
        snap = _snap()
        tahsis = tahsis_hesapla(snap, YatirimProfili())
        senaryolar = senaryo_analizi_uret(snap, tahsis, 153)
        self.assertEqual(len(senaryolar), 3)
        adlar = {s.ad for s in senaryolar}
        self.assertIn("Kur şoku", adlar)
        self.assertIn("CDS stresi", adlar)
        self.assertIn("TCMB faiz kararı", adlar)

    def test_cds_stresi_tavan_duser(self):
        snap = _snap()
        tahsis = tahsis_hesapla(snap, YatirimProfili())
        cds_s = next(s for s in senaryo_analizi_uret(snap, tahsis) if s.ad == "CDS stresi")
        self.assertIn(str(int(config.SENARYO_CDS_STRES_BP)), cds_s.ozet)


if __name__ == "__main__":
    unittest.main()
