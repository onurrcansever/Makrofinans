# -*- coding: utf-8 -*-
"""TL reel negatifken tahsis ve danışman sinyali tutarlılığı."""
import unittest
from unittest.mock import patch

import config
from advice_engine import danisman_raporu_olustur
from allocation_engine import tahsis_hesapla, tl_reel_negatif_max_oran
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma


def _snap():
    veri = PiyasaVerisi(
        eur_try=35.0,
        usd_try=32.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=280.0,
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


def _negatif_mevduat(reel: float = -3.7) -> MevduatKarsilastirma:
    return MevduatKarsilastirma(
        oranlar=[],
        enflasyon=35.0,
        en_iyi_vade="TL 1 yıl",
        en_iyi_net=32.0,
        en_iyi_reel=reel,
        eur_mevduat_net=2.0,
        tl_mevduat_kazanir=False,
        ozet="test",
        profil_vade="TL 1 yıl",
        profil_vade_net=31.3,
        profil_vade_reel=reel,
        profil_vade_eur_tahmini=-1.7,
    )


class TlReelNegatifTest(unittest.TestCase):
    def test_reel_tavan_kademeli(self):
        self.assertGreater(tl_reel_negatif_max_oran(1.0), 0.4)
        self.assertEqual(tl_reel_negatif_max_oran(-1.0), config.TL_REEL_NEGATIF_MAX_ORAN)
        self.assertEqual(tl_reel_negatif_max_oran(-3.7), config.TL_REEL_COK_NEGATIF_MAX_ORAN)

    @patch("allocation_engine.mevduat_analizi")
    def test_uzun_vade_tl_sinirlanir(self, mock_mev):
        mock_mev.return_value = _negatif_mevduat(-3.7)
        snap = _snap()
        profil = YatirimProfili(risk="orta", vade="uzun")
        tahsis = tahsis_hesapla(snap, profil)
        self.assertTrue(tahsis.tl_reel_sinirlandi)
        self.assertLessEqual(
            tahsis.agirliklar["tl_deposit"],
            config.TL_REEL_COK_NEGATIF_MAX_ORAN + 0.001,
        )
        self.assertAlmostEqual(tahsis.tl_mevduat_reel, -3.7)

    @patch("allocation_engine.mevduat_analizi")
    def test_danisman_guclu_alim_vermez(self, mock_mev):
        mock_mev.return_value = _negatif_mevduat(-3.7)
        snap = _snap()
        profil = YatirimProfili(risk="orta", vade="uzun")
        tahsis = tahsis_hesapla(snap, profil)
        mevduat = _negatif_mevduat(-3.7)
        rapor = danisman_raporu_olustur(snap, tahsis, profil, mevduat=mevduat)
        tl = next(v for v in rapor.varliklar if v.anahtar == "tl_deposit")
        self.assertNotIn(tl.sinyal, ("GUCLU_AL", "AL"))
        kritik = [
            b for b in rapor.denetim.bulgular
            if b.seviye == "KRITIK" and "mevduat analizi çelişiyor" in b.baslik
        ]
        self.assertEqual(kritik, [])


if __name__ == "__main__":
    unittest.main()
