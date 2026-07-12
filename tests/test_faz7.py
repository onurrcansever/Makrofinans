# -*- coding: utf-8 -*-
"""Faz 7 — temel skor ve bileşik karar testleri."""
import unittest

from alim_uygunluk import alim_aksiyon_hucre
from investor_profile import YatirimProfili
from stock_scanner import HisseAnaliz
from temel_skor import (
    bilesik_skor_hesapla,
    temel_skor_hesapla,
)


def _etf(sembol, ad, sektor, zirve=50, teknik=70, revolut=""):
    return HisseAnaliz(
        sembol=sembol,
        ad=ad,
        piyasa="ETF",
        fiyat=100.0,
        degisim_1g=0.1,
        degisim_1ay=2.0,
        degisim_3ay=5.0,
        degisim_1y=8.0,
        rsi=55,
        sma20=98,
        sma50=95,
        sinyal="TREND_ALIM",
        skor=teknik,
        gerekce="test",
        sektor=sektor,
        teknik_skor=teknik,
        zirve_52h_pct=zirve,
        varlik_turu="etf",
        revolut_ticker=revolut or sembol.split(".")[0],
    )


class Faz7TemelSkorTest(unittest.TestCase):
    def test_notr_vagp_temel_yuksek_eqqq(self):
        vagp = _etf("VAGP.L", "Vanguard Bond", "tahvil", zirve=40, teknik=60)
        eqqq = _etf("EQQQ.L", "Nasdaq 100", "teknoloji", zirve=85, teknik=75)
        t_v, _, _, _, _ = temel_skor_hesapla(vagp, "NOTR", "orta", "orta", vol_30g=8)
        t_e, _, _, _, _ = temel_skor_hesapla(eqqq, "NOTR", "orta", "orta", vol_30g=22)
        self.assertGreater(t_v, t_e)

    def test_risk_on_eqqq_temel_yuksek_vagp(self):
        vagp = _etf("VAGP.L", "Vanguard Bond", "tahvil", zirve=40, teknik=60)
        eqqq = _etf("EQQQ.L", "Nasdaq 100", "teknoloji", zirve=55, teknik=75)
        t_v, _, _, _, _ = temel_skor_hesapla(vagp, "RISK_ON", "orta", "orta", vol_30g=8)
        t_e, _, _, _, _ = temel_skor_hesapla(eqqq, "RISK_ON", "orta", "orta", vol_30g=22)
        self.assertGreater(t_e, t_v)

    def test_kisa_3_vade_cspx_bekle(self):
        from alim_uygunluk import alim_uygunluk_uygula

        cspx = _etf("CSPX.L", "S&P 500", "abd", zirve=45, teknik=85)
        _, vade_p, vade_ok, _, _ = temel_skor_hesapla(
            cspx, "NOTR", "kisa_3", "orta", vol_30g=15,
        )
        self.assertEqual(vade_p, 0.0)
        self.assertFalse(vade_ok)
        cspx.temel_skor = 55
        cspx.bilesik_skor = bilesik_skor_hesapla(85, 55)
        cspx.vade_uygun = False
        cspx.vade_uyum_puani = 0
        alim_uygunluk_uygula([cspx], {cspx.sembol}, 55, profil=YatirimProfili(vade="kisa_3"))
        self.assertEqual(alim_aksiyon_hucre(cspx), "BEKLE")
        self.assertIn("Vade uyumsuz", cspx.alim_uygun_not)

    def test_teknik_yuksek_temel_dusuk_alamaz(self):
        from alim_uygunluk import alim_uygunluk_uygula

        emim = _etf("EMIM.L", "EM IMI", "gelisen", zirve=95, teknik=100)
        temel, _, vade_ok, _, _ = temel_skor_hesapla(
            emim, "NOTR", "kisa_3", "dusuk", vol_30g=28,
        )
        bilesik = bilesik_skor_hesapla(100, temel)
        emim.temel_skor = temel
        emim.bilesik_skor = bilesik
        emim.vade_uygun = vade_ok
        emim.vade_uyum_puani = 0
        alim_uygunluk_uygula([emim], {emim.sembol}, 55, profil=YatirimProfili(vade="kisa_3", risk="dusuk"))
        self.assertLess(bilesik, 80)
        self.assertNotEqual(alim_aksiyon_hucre(emim), "AL")

    def test_bilesik_agirlik(self):
        b = bilesik_skor_hesapla(100, 50)
        self.assertAlmostEqual(b, 70.0, places=1)


if __name__ == "__main__":
    unittest.main()
