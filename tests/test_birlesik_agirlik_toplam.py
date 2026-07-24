# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from allocation_engine import tahsis_hesapla
from birlesik_oneri import birlesik_oneri_olustur
from investor_profile import YatirimProfili
from kullanici_portfoy import KullaniciPortfoy
from macro_data import demo_snapshot
from tefas_data import FonPerformans, TefasTaramaSonuc


class BirlesikAgirlikToplamTest(unittest.TestCase):
    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_hedef_yuzde_yuz(self, mock_yk):
        mock_yk.return_value = TefasTaramaSonuc(
            fonlar=[
                FonPerformans(
                    kod="YLB",
                    ad="YAPI KREDİ PP",
                    kisa_ad="PP",
                    kategori="para_piyasasi",
                    kategori_etiket="PP",
                    para_birimi="TL",
                    para_etiket="TL",
                    fiyat=1.7,
                    getiri_3a=8.0,
                    getiri_ybb=30.0,
                    dagilim_ozet="Bono/Repo %60",
                    etkin_kategori="borclanma",
                )
            ]
        )
        snap = demo_snapshot()
        profil = YatirimProfili(risk="orta", vade="orta_12")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(para_birimi="EUR", toplam=50000.0)
        oneri = birlesik_oneri_olustur(
            snap, tahsis, profil, kp, mevduat_reel=2.0, tefas_istek=True,
        )
        toplam = sum(h.agirlik_pct for h in oneri.hedef_tablo)
        self.assertAlmostEqual(toplam, 100.0, delta=1.5)

        tl = next((h for h in oneri.hedef_tablo if h.kategori == "TL vadeli mevduat"), None)
        tefas = next((h for h in oneri.hedef_tablo if h.kategori == "TEFAS fon"), None)
        if tl and tefas:
            makro_tl = tahsis.agirliklar.get("tl_deposit", 0) * 100
            self.assertAlmostEqual(tl.agirlik_pct + tefas.agirlik_pct, makro_tl, delta=1.5)

        eur = next((h for h in oneri.hedef_tablo if "EUR" in h.kategori), None)
        usd = next((h for h in oneri.hedef_tablo if "USD" in h.kategori), None)
        etf = next((h for h in oneri.hedef_tablo if h.kategori.startswith("ETF")), None)
        if etf:
            fx = (eur.agirlik_pct if eur else 0) + (usd.agirlik_pct if usd else 0)
            makro_fx = (
                tahsis.agirliklar.get("eur_cash", 0) + tahsis.agirliklar.get("usd_cash", 0)
            ) * 100
            self.assertAlmostEqual(fx + etf.agirlik_pct, makro_fx, delta=2.0)


if __name__ == "__main__":
    unittest.main()
