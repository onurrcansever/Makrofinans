# -*- coding: utf-8 -*-
import unittest

from investor_profile import YatirimProfili
from portfoy_yoneticisi import (
    yonetici_plani_olustur,
    yonetici_pozisyon_plani,
    yonetici_tablo_metni,
    yonetici_oncelikli,
)
from stock_scanner import HisseAnaliz


def _fx(eur=53.0, usd=47.0, gbp=1.34):
    from types import SimpleNamespace
    return SimpleNamespace(eur_try=eur, usd_try=usd, gbp_usd=gbp, eur_usd=usd / eur)


def _hisse(**kw):
    base = dict(
        sembol="TSLA",
        ad="Tesla",
        piyasa="NASDAQ",
        fiyat=400.0,
        degisim_1g=0.5,
        degisim_1ay=-2.0,
        degisim_3ay=10.0,
        degisim_1y=20.0,
        rsi=55.0,
        sma20=395.0,
        sma50=380.0,
        sma200=350.0,
        sinyal="TREND_ALIM",
        skor=75.0,
        gerekce="test",
        sektor="buyume",
        teknik_skor=80.0,
        temel_skor=60.0,
        bilesik_skor=68.0,
        zirve_52h_pct=95.0,
        alim_uygun="SINIRLI",
        vade_uygun=True,
        varlik_turu="hisse",
    )
    base.update(kw)
    return HisseAnaliz(**{k: base[k] for k in base if k in HisseAnaliz.__dataclass_fields__})


def _etf(**kw):
    return _hisse(
        sembol="VWCE.DE",
        ad="VWCE",
        piyasa="ETF",
        sektor="hisse_global",
        varlik_turu="etf",
        **kw,
    )


class PortfoyYoneticisiTest(unittest.TestCase):
    def test_zirve_bekle_hedef_fiyat(self):
        h = _hisse(zirve_52h_pct=95.0, alim_uygun="IZLE")
        yonetici_plani_olustur(h, YatirimProfili(risk="orta", vade="kisa_6"))
        self.assertEqual(h.yonetici_aksiyon, "BEKLE")
        self.assertIsNotNone(h.yonetici_alim)
        self.assertLess(h.yonetici_alim, h.fiyat)

    def test_core_etf_uzun_kademeli(self):
        h = _etf(zirve_52h_pct=99.0, alim_uygun="SINIRLI")
        yonetici_plani_olustur(h, YatirimProfili(risk="yuksek", vade="uzun"))
        self.assertEqual(h.yonetici_aksiyon, "KADEMELI")
        self.assertIn("parça", h.yonetici_ozet.lower())

    def test_uygun_al(self):
        h = _hisse(alim_uygun="UYGUN", zirve_52h_pct=60.0, sinyal="TREND_ALIM")
        yonetici_plani_olustur(h, YatirimProfili())
        self.assertEqual(h.yonetici_aksiyon, "AL")

    def test_tablo_metni_pb(self):
        h = _hisse(zirve_52h_pct=95.0)
        yonetici_plani_olustur(h, YatirimProfili())
        metin = yonetici_tablo_metni(h, "USD", _fx())
        self.assertIn("al:", metin.lower())

    def test_oncelikli_core_etf(self):
        a = _etf(zirve_52h_pct=99.0, bilesik_skor=67)
        b = _hisse(bilesik_skor=85)
        yonetici_plani_olustur(a, YatirimProfili(risk="yuksek", vade="uzun"))
        yonetici_plani_olustur(b, YatirimProfili(risk="yuksek", vade="uzun"))
        top = yonetici_oncelikli([a, b], n=2)
        self.assertEqual(top[0].sembol, "VWCE.DE")

    def test_pozisyon_stop_maliyet_alti(self):
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger

        p = VarlikPozisyon(id="2", tur="hisse", sembol="TEST", miktar=100, maliyet=35)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="100", alim_birim=0.35, guncel_birim=0.3913,
            maliyet_deger=35, guncel_deger=39.13, kar_zarar=4.13, kar_zarar_pct=11.8,
            para="EUR", getiriler={},
        )
        plan = yonetici_pozisyon_plani(p, pd_, fx=_fx())
        self.assertIn("Tut", plan)
        self.assertIn("Stop", plan)
        self.assertNotIn("Sat:", plan)

    def test_tarama_sat_gostermez(self):
        h = _hisse(zirve_52h_pct=95.0, sma200=0.38, fiyat=0.3913)
        yonetici_plani_olustur(h, YatirimProfili())
        metin = yonetici_tablo_metni(h, "EUR", _fx())
        self.assertNotIn("sat", metin.lower())

    def test_pozisyon_kolonlari(self):
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from portfoy_yoneticisi import yonetici_pozisyon_kolonlari

        p = VarlikPozisyon(id="2", tur="hisse", sembol="TEST", miktar=100, maliyet=35)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="100", alim_birim=0.35, guncel_birim=0.3913,
            maliyet_deger=35, guncel_deger=39.13, kar_zarar=4.13, kar_zarar_pct=11.8,
            para="EUR", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, fx=_fx())
        self.assertEqual(kol["Emir"], "Tut")
        self.assertNotEqual(kol["Stop"], "—")

    def test_pozisyon_plani_nakit(self):
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from portfoy_yoneticisi import yonetici_pozisyon_kolonlari

        p = VarlikPozisyon(id="1", tur="nakit_tl", miktar=10000, maliyet=10000)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="10.000 TL", alim_birim=1, guncel_birim=1,
            maliyet_deger=10000, guncel_deger=10000, kar_zarar=0, kar_zarar_pct=0,
            para="TL", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, fx=_fx())
        self.assertEqual(kol["Emir"], "Tut")


if __name__ == "__main__":
    unittest.main()
