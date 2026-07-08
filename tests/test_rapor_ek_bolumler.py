# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from birlesik_oneri import AracDagilimSatir, BirlesikOneri, HedefSatir
from kullanici_portfoy import KullaniciPortfoy
from macro_data import demo_snapshot
from rapor_ek_bolumler import (
    _sidebar_hedef,
    birlesik_oneri_html_blok,
    varliklarim_html_blok,
)
from varliklarim import VarlikPortfoy, VarlikPozisyon, VarlikStore


class RaporEkBolumlerTest(unittest.TestCase):
    def test_sidebar_hedef_tl(self):
        snap = demo_snapshot()
        kp = KullaniciPortfoy(para_birimi="TL", toplam=1_200_000.0)
        hedef = _sidebar_hedef(kp, "TL", snap)
        self.assertAlmostEqual(hedef, 1_200_000.0, delta=1.0)

    def test_birlesik_html_icerik(self):
        oneri = BirlesikOneri(
            ozet="test ozet",
            hedef_tablo=[
                HedefSatir("TL vadeli mevduat", "banka", 22.0, 220_000.0, "TL"),
            ],
            arac_dagilim=[
                AracDagilimSatir("TEFAS fon", "YIV", "fon", 7.0, 50.0, 70_000.0, "TL", "GUCLU"),
            ],
        )
        html = birlesik_oneri_html_blok(
            oneri,
            para_birimi="TL",
            toplam_eur=22_430.0,
            eur_try=53.5,
            esc=lambda x: str(x),
        )
        self.assertIn("Detaylı Hedef", html)
        self.assertIn("YIV", html)
        self.assertIn("TEFAS fon", html)

    @patch("rapor_ek_bolumler.portfoy_degerle")
    def test_varlik_html_pozisyon(self, mock_deger):
        from varlik_fiyat import PortfoyDeger, PozisyonDeger

        poz = VarlikPozisyon(
            id="p1",
            tur="nakit_tl",
            miktar=1000,
            maliyet=1000,
            para_birimi="TL",
            alim_tarihi="2026-07-08",
        )
        store = VarlikStore(
            aktif_id="a",
            goruntuleme_pb="TL",
            portfoyler=[VarlikPortfoy(id="a", ad="Ana", pozisyonlar=[poz])],
        )
        mock_deger.return_value = PortfoyDeger(
            pozisyonlar=[
                PozisyonDeger(
                    pozisyon=poz,
                    guncel_birim=1.0,
                    alim_birim=1.0,
                    miktar_goster="1.000 TL",
                    guncel_deger=1000,
                    maliyet_deger=1000,
                    kar_zarar=0,
                    kar_zarar_pct=0,
                    para="TL",
                    getiriler={"1G": 0.0, "1A": 0.0},
                )
            ],
            toplam={"TL": 1000, "EUR": 18, "USD": 21},
            maliyet_toplam={"TL": 1000, "EUR": 18, "USD": 21},
            agirlikli_getiri={"1G": 0.0, "1H": 0.0, "1A": 0.0, "3A": 0.0, "6A": 0.0},
        )
        html = varliklarim_html_blok(
            store,
            demo_snapshot(),
            KullaniciPortfoy(para_birimi="TL", toplam=1000),
            esc=lambda x: str(x),
        )
        self.assertIn("Ana", html)
        self.assertIn("nakit", html.lower())


if __name__ == "__main__":
    unittest.main()
