# -*- coding: utf-8 -*-
"""TL makro haber riski — faiz indirimi beklentisi, erken seçim anormal sıklık."""
import os
import tempfile
import unittest
from unittest.mock import patch

import config
from decision_engine import PiyasaVerisi, karar_ver
from macro_data import MacroSnapshot
from regime import rejim_tespit
from tl_makro_risk import TlMakroRiskSonuc, _anormal, _secim_anormal, tl_makro_risk_tara


def _snap(cds=240.0, vix=14.0, savas=100, siyasi=10, tl_makro=False, faiz_haber=0, secim=0):
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
        tl_makro_risk_aktif=tl_makro,
        tl_faiz_indirim_haber=faiz_haber,
        tl_erken_secim_haber=secim,
        tl_erken_secim_anormal=tl_makro and secim > 0,
    )
    return MacroSnapshot(veri=veri, vix=vix, enflasyon_tr_yillik=29.0, eur_usd=1.08)


class TlMakroRiskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["MARKET_CACHE_DB"] = os.path.join(self.tmp, "test.db")

    def test_jeopolitik_yuksek_tl_firsat_kapanmaz(self):
        """Orta Doğu haber yoğunluğu tek başına TL fırsatı kapatmamalı."""
        snap = _snap(savas=config.SAVAS_RISK_YUKSEK_ESIGI + 50, tl_makro=False)
        r = rejim_tespit(snap)
        self.assertEqual(r.rejim, "TL_FIRSAT")

    def test_tl_makro_risk_tl_firsat_kapatir(self):
        snap = _snap(savas=100, tl_makro=True, faiz_haber=12)
        r = rejim_tespit(snap)
        self.assertNotEqual(r.rejim, "TL_FIRSAT")
        self.assertTrue(any("faiz indirimi" in a for a in r.adimlar))

    def test_kapi_1c_tavan_carpani(self):
        veri = PiyasaVerisi(
            eur_try=35.0,
            cds_5y_bp=240.0,
            rezerv_artiyor=True,
            tl_makro_risk_aktif=True,
            tl_faiz_indirim_haber=10,
            tl_erken_secim_haber=20,
            tl_erken_secim_anormal=True,
        )
        sonuc = karar_ver(veri)
        self.assertTrue(any("Kapı 1d" in a for a in sonuc.adimlar))
        self.assertLess(sonuc.tavan_oran, config.CDS_ESIK_TABLOSU[-1][1])

    @patch("risk_scan.google_news_sayisi")
    def test_tarama_sonucu(self, mock_say):
        mock_map = {
            config.TL_MAKRO_FAIZ_SORGULARI[0]: 3,
            config.TL_MAKRO_FAIZ_SORGULARI[1]: 15,
            config.TL_MAKRO_FAIZ_SORGULARI[2]: 2,
        }
        for s in config.TL_MAKRO_SECIM_SORGULARI:
            mock_map[s] = 5
        mock_say.side_effect = lambda s, saat=48: mock_map.get(s, 0)
        sonuc = tl_makro_risk_tara(saat=48)
        self.assertEqual(sonuc.faiz_indirim_sayisi, 15)
        self.assertEqual(sonuc.erken_secim_sayisi, 5)
        self.assertTrue(sonuc.faiz_indirim_yuksek)
        self.assertFalse(sonuc.erken_secim_anormal)
        self.assertTrue(sonuc.tl_makro_risk_aktif)

    def test_secim_karar_esigi_altinda_anormal_degil(self):
        with patch("tl_makro_risk.taban_median", return_value=5.0):
            self.assertFalse(
                _secim_anormal(4, "erken_secim", 20, 1.5)
            )

    def test_anormal_esik(self):
        with patch("tl_makro_risk.taban_median", return_value=10.0):
            self.assertTrue(_anormal(16, "erken_secim", 8, 1.5))
            self.assertFalse(_anormal(14, "erken_secim", 8, 1.5))


if __name__ == "__main__":
    unittest.main()
