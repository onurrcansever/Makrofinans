# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from arac_secici import (
    dilim_karari_altin,
    dilim_karari_fx,
    dilim_karari_tl,
    maliyet_suruklenmesi_yillik,
)


class AracSeciciTest(unittest.TestCase):
    def test_maliyet_stopaj_suruk(self):
        m, k = maliyet_suruklenmesi_yillik(
            tgo_pct=1.0,
            stopaj_orani_pct=17.5,
            beklenen_getiri_pct=20.0,
        )
        self.assertAlmostEqual(k["stopaj_suruk"], 3.5, places=2)
        self.assertAlmostEqual(m, 4.5, places=2)

    def test_tl_mevduat_kazanir(self):
        mev = SimpleNamespace(profil_vade_net=35.0)
        fon = SimpleNamespace(
            kod="YLB",
            ad="YAPI KREDİ PORTFÖY PARA PİYASASI FONU",
            kisa_ad="PP",
            kategori="para_piyasasi",
            hisse_pct=None,
            getiri_3a=2.0,
            getiri_ybb=8.0,
            tgo_pct=2.0,
            oneri="AL",
        )
        k = dilim_karari_tl(
            tl_w=0.20,
            mevduat_ozet=mev,
            fon_adaylari=[fon],
            kisa_vade=False,
        )
        self.assertIsNotNone(k)
        self.assertEqual(k.kazanan.tur, "mevduat")
        self.assertEqual(k.dilim_pay, 0.0)

    def test_tl_fon_kazanir_dusuk_mevduat(self):
        mev = SimpleNamespace(profil_vade_net=5.0)
        fon = SimpleNamespace(
            kod="YLB",
            ad="YAPI KREDİ PORTFÖY PARA PİYASASI FONU",
            kisa_ad="PP",
            kategori="para_piyasasi",
            hisse_pct=None,
            getiri_3a=8.0,
            getiri_ybb=28.0,
            tgo_pct=0.5,
            oneri="AL",
        )
        k = dilim_karari_tl(
            tl_w=0.20,
            mevduat_ozet=mev,
            fon_adaylari=[fon],
            kisa_vade=False,
        )
        self.assertEqual(k.kazanan.tur, "tefas")
        self.assertGreater(k.dilim_pay, 0.0)

    def test_eur_mevduat_kisa_vade(self):
        mev = SimpleNamespace(eur_mevduat_net=1.5, oranlar=[])
        k = dilim_karari_fx(
            pb="EUR",
            fx_w=0.30,
            mevduat_ozet=mev,
            fon_adaylari=[],
            etf_adaylari=[("CSPX", "S&P 500", "abd")],
            kisa_vade=True,
        )
        self.assertEqual(k.kazanan.tur, "mevduat")
        self.assertEqual(k.dilim_pay, 0.0)

    def test_altin_fon_vs_fiziki(self):
        fon = SimpleNamespace(
            kod="KZL",
            ad="KUVEYT TÜRK PORTFÖY ALTIN KATILIM FONU",
            kisa_ad="Altın",
            kategori="altin_emtia",
            hisse_pct=None,
            getiri_3a=12.0,
            getiri_ybb=40.0,
            tgo_pct=0.3,
            oneri="AL",
        )
        k = dilim_karari_altin(
            gold_w=0.25,
            altin_3a_momentum=2.0,
            fon_adaylari=[fon],
            kisa_vade=False,
        )
        self.assertIsNotNone(k)
        self.assertIn(k.kazanan.tur, ("tefas", "etf", "fiziki"))


if __name__ == "__main__":
    unittest.main()
