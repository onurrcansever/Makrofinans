# -*- coding: utf-8 -*-
"""Stopaj ve kripto tutarlılık testleri."""
import unittest

import config
from allocation_engine import tahsis_hesapla
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from yapikredi_rates import stopaj_orani


def _snap(rejim_inputs=None):
    veri = PiyasaVerisi(
        eur_try=35.0,
        usd_try=32.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=240.0,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=10,
        savas_risk_makale_sayisi=0,
        savas_risk_guvenilir=True,
    )
    return MacroSnapshot(
        veri=veri,
        vix=18.0,
        enflasyon_tr_yillik=35.0,
        eur_usd=1.08,
        btc_usd=95000.0,
        btc_3m_degisim=10.0,
    )


class StopajKriptoTest(unittest.TestCase):
    def test_tl_stopaj_15_yuzde(self):
        self.assertEqual(stopaj_orani(92, "TL"), 0.15)
        self.assertEqual(stopaj_orani(181, "TL"), 0.15)
        self.assertEqual(stopaj_orani(365, "TL"), 0.15)

    def test_notr_orta_risk_kripto_sifir(self):
        snap = _snap()
        profil = YatirimProfili(risk="orta", vade="kisa")
        tahsis = tahsis_hesapla(snap, profil)
        self.assertNotEqual(tahsis.rejim.rejim, "RISK_ON")
        self.assertEqual(tahsis.agirliklar.get("crypto", 0), 0.0)

    def test_dusuk_risk_kripto_sifir(self):
        snap = _snap()
        profil = YatirimProfili(risk="dusuk", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        self.assertEqual(tahsis.agirliklar.get("crypto", 0), 0.0)


if __name__ == "__main__":
    unittest.main()
