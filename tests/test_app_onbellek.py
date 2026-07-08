# -*- coding: utf-8 -*-
import unittest

from app_onbellek import onbellek_anahtari, _mevduat_imza
from kullanici_portfoy import KullaniciPortfoy, MevcutPozisyon


class AppOnbellekTest(unittest.TestCase):
    def test_anahtar_portfoy_tutari(self):
        kp1 = KullaniciPortfoy(para_birimi="TL", toplam=1_200_000)
        kp2 = KullaniciPortfoy(para_birimi="TL", toplam=900_000)
        k1 = onbellek_anahtari(
            tick=0, profil_anahtar="orta_orta_3", kp=kp1,
            canli_mod=True, haber_tara=False, bt_ay=12,
        )
        k2 = onbellek_anahtari(
            tick=0, profil_anahtar="orta_orta_3", kp=kp2,
            canli_mod=True, haber_tara=False, bt_ay=12,
        )
        self.assertNotEqual(k1, k2)

    def test_mevduat_imza(self):
        kp = KullaniciPortfoy(
            para_birimi="TL",
            toplam=1_000_000,
            pozisyonlar=[
                MevcutPozisyon(tur="tl_mevduat", tutar=500_000, para_birimi="TL"),
            ],
        )
        self.assertIn("tl_mevduat", _mevduat_imza(kp))


if __name__ == "__main__":
    unittest.main()
