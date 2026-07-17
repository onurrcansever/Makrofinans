# -*- coding: utf-8 -*-
import unittest

from investor_profile import YatirimProfili
from portfoy_yoneticisi import (
    yonetici_plani_olustur,
    yonetici_pozisyon_plani,
    yonetici_tablo_metni,
    yonetici_oncelikli,
    yonetici_pozisyon_kolonlari,
    pozisyon_emir_hesapla,
    pozisyon_sinyal_bilgisi,
    pozisyon_oneri_etiket,
    POZ_COL_SINYAL,
    POZ_COL_ONERI,
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
        self.assertIn("Elde tut", plan)
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

        p = VarlikPozisyon(id="2", tur="hisse", sembol="TEST", miktar=100, maliyet=35)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="100", alim_birim=0.35, guncel_birim=0.3913,
            maliyet_deger=35, guncel_deger=39.13, kar_zarar=4.13, kar_zarar_pct=11.8,
            para="EUR", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, fx=_fx())
        self.assertEqual(pozisyon_oneri_etiket(kol[POZ_COL_ONERI]), "Elde tut")
        self.assertEqual(kol[POZ_COL_SINYAL], "—")
        self.assertNotEqual(kol["Stop"], "—")
        self.assertIn("tip", kol[POZ_COL_ONERI])

    def test_pozisyon_v2_azalt_kar_al(self):
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from types import SimpleNamespace

        h = _hisse(
            sembol="CSCO", signal_v2_decision="AZALT", signal_v2_score=38.0,
            fiyat=70.0, yonetici_alim=65.0,
        )
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="3", tur="hisse_us", sembol="CSCO", miktar=10, maliyet=600)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="10", alim_birim=60.0, guncel_birim=70.0,
            maliyet_deger=600, guncel_deger=700, kar_zarar=100, kar_zarar_pct=16.7,
            para="USD", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, tarama=tarama, fx=_fx())
        self.assertEqual(kol[POZ_COL_SINYAL], "AZALT")
        self.assertEqual(pozisyon_oneri_etiket(kol[POZ_COL_ONERI]), "Kâr al")

    def test_pozisyon_v2_al_ekle(self):
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from types import SimpleNamespace

        h = _hisse(
            sembol="AAPL", signal_v2_decision="AL", signal_v2_score=72.0,
            fiyat=180.0, signal_v2_al_price=170.0,
        )
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="4", tur="hisse_us", sembol="AAPL", miktar=5, maliyet=950)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="5", alim_birim=190.0, guncel_birim=171.0,
            maliyet_deger=950, guncel_deger=855, kar_zarar=-95, kar_zarar_pct=-10.0,
            para="USD", getiriler={},
        )
        self.assertEqual(pozisyon_emir_hesapla(-10.0, "AL", tur="hisse_us"), "Ekle")
        kol = yonetici_pozisyon_kolonlari(p, pd_, tarama=tarama, fx=_fx())
        self.assertEqual(pozisyon_oneri_etiket(kol[POZ_COL_ONERI]), "Ekleme düşün")
        self.assertEqual(kol[POZ_COL_SINYAL], "AL")

    def test_pozisyon_kar_al_esik(self):
        self.assertEqual(pozisyon_emir_hesapla(26.0, "İZLE"), "Sat")
        self.assertEqual(pozisyon_emir_hesapla(18.0, "BEKLE"), "Kâr Al")
        self.assertEqual(pozisyon_emir_hesapla(18.0, "AZALT"), "Kâr Al")

    def test_pozisyon_sinyal_tefas(self):
        from types import SimpleNamespace

        fon = SimpleNamespace(kod="TI2", oneri="ZAYIF", skor=35.0)
        tefas = SimpleNamespace(fonlar=[fon])
        s = pozisyon_sinyal_bilgisi("tefas", "TI2", tefas_skorlu=tefas)
        self.assertEqual(s["karar"], "AZALT")
        self.assertEqual(pozisyon_emir_hesapla(8.0, s["karar"], tur="tefas"), "Azalt")

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
        self.assertEqual(pozisyon_oneri_etiket(kol[POZ_COL_ONERI]), "Elde tut")

    def test_pozisyon_oneri_pasif_bekle_tooltip(self):
        from portfoy_yoneticisi import pozisyon_oneri_hucre

        h = pozisyon_oneri_hucre("Bekle", "BEKLE", -7.0, tur="altin")
        self.assertEqual(h["label"], "Pasif bekle")
        self.assertIn("eklemeyin", h["tip"].lower())
        h2 = pozisyon_oneri_hucre("Tut", "İZLE", 0.9, tur="tefas")
        self.assertEqual(h2["label"], "Elde tut")
        self.assertIn("Elde tutun", h2["tip"])

    def test_bist_hisse_stop_quote_currency(self):
        """ARCLK.IS — TL fiyat, sembol settlement dönüşümü olmadan Stop/Ekle."""
        from types import SimpleNamespace
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger

        h = _hisse(sembol="ARCLK.IS", fiyat=120.0, signal_v2_decision="İZLE", quote_currency="TRY")
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="bist1", tur="hisse", sembol="ARCLK.IS", miktar=10, maliyet=1000)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="10", alim_birim=100.0, guncel_birim=120.0,
            maliyet_deger=1000, guncel_deger=1200, kar_zarar=200, kar_zarar_pct=20.0,
            para="TL", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, tarama=tarama, fx=_fx(), gosterim_pb="EUR")
        self.assertNotEqual(kol["Stop"], "—")
        self.assertIn("EUR", kol["Stop"])

    def test_emtia_ekle_oz_to_gram_eur(self):
        """GC=F al_price USD/oz → gram TL → EUR; ~0.629 birim hatası olmamalı."""
        from types import SimpleNamespace
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from emtia_universe import gram_tl_from_oz

        spot_oz = 4000.0
        al_oz = 3800.0  # %5 spot altı — sanity guard içinde
        usd_try = 35.0
        eur_try = 35.5
        guncel_tl = gram_tl_from_oz(spot_oz, usd_try)

        h = SimpleNamespace(
            sembol="GC=F",
            signal_v2_decision="İZLE",
            signal_v2_al_price=al_oz,
            quote_currency="USD",
        )
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="au", tur="altin", sembol="", miktar=10, maliyet=40000)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="10 gr", alim_birim=guncel_tl * 1.03,
            guncel_birim=guncel_tl, maliyet_deger=40000, guncel_deger=40000,
            kar_zarar=-1200, kar_zarar_pct=-2.6, para="TL", getiriler={},
        )
        fx = _fx(eur=eur_try, usd=usd_try)
        kol = yonetici_pozisyon_kolonlari(
            p, pd_, tarama=tarama, fx=fx, gosterim_pb="EUR",
        )
        self.assertNotEqual(kol["Ekle"], "—")
        ekle_eur = float(kol["Ekle"].split()[0].replace(",", ""))
        guncel_eur = guncel_tl / eur_try
        ratio = ekle_eur / guncel_eur
        self.assertAlmostEqual(ratio, al_oz / spot_oz, places=2)
        bug_ratio = al_oz * 31.1034768 / (spot_oz * usd_try)
        self.assertNotAlmostEqual(ratio, bug_ratio, delta=0.02)

    def test_emtia_derin_ekle_karantina(self):
        """52H-derin seviye >%15 sapma → Ekle gizlenir (tarama guard ile uyumlu)."""
        from types import SimpleNamespace
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from emtia_universe import gram_tl_from_oz

        spot_oz = 3547.0
        al_oz = 2507.0
        guncel_tl = gram_tl_from_oz(spot_oz, 35.0)
        h = SimpleNamespace(
            sembol="GC=F", signal_v2_decision="İZLE", signal_v2_al_price=al_oz,
            quote_currency="USD",
        )
        p = VarlikPozisyon(id="au2", tur="altin", sembol="", miktar=10, maliyet=40000)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="10 gr", alim_birim=guncel_tl,
            guncel_birim=guncel_tl, maliyet_deger=40000, guncel_deger=40000,
            kar_zarar=0, kar_zarar_pct=0, para="TL", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(
            p, pd_, tarama=SimpleNamespace(hisseler=[h]),
            fx=_fx(eur=35.5, usd=35.0), gosterim_pb="EUR",
        )
        self.assertEqual(kol["Ekle"], "—")

    def test_emtia_altin_gumus_farkli_ekle_orani(self):
        from types import SimpleNamespace
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger
        from emtia_universe import gram_tl_from_oz

        usd_try = 35.0
        eur_try = 35.5
        fx = _fx(eur=eur_try, usd=usd_try)

        def _ratio(tur, spot_oz, al_oz):
            guncel_tl = gram_tl_from_oz(spot_oz, usd_try)
            sym = "GC=F" if tur == "altin" else "SI=F"
            h = SimpleNamespace(
                sembol=sym, signal_v2_decision="AL", signal_v2_al_price=al_oz,
                quote_currency="USD",
            )
            p = VarlikPozisyon(id=tur, tur=tur, sembol="", miktar=1, maliyet=1000)
            pd_ = PozisyonDeger(
                pozisyon=p, miktar_goster="1", alim_birim=guncel_tl * 1.05,
                guncel_birim=guncel_tl, maliyet_deger=1000, guncel_deger=1000,
                kar_zarar=-50, kar_zarar_pct=-5.0, para="TL", getiriler={},
            )
            kol = yonetici_pozisyon_kolonlari(
                p, pd_, tarama=SimpleNamespace(hisseler=[h]), fx=fx, gosterim_pb="EUR",
            )
            ekle_eur = float(kol["Ekle"].split()[0].replace(",", ""))
            return ekle_eur / (guncel_tl / eur_try)

        r_au = _ratio("altin", 4000.0, 3800.0)
        r_ag = _ratio("gumus", 55.0, 50.0)
        self.assertNotAlmostEqual(r_au, r_ag, delta=0.02)

    def test_pozisyon_ekle_sanity_karantina(self):
        from types import SimpleNamespace
        from varliklarim import VarlikPozisyon
        from varlik_fiyat import PozisyonDeger

        h = _hisse(
            sembol="AAPL", signal_v2_decision="AL", signal_v2_score=72.0,
            fiyat=180.0, signal_v2_al_price=90.0,
        )
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="5", tur="hisse_us", sembol="AAPL", miktar=5, maliyet=950)
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="5", alim_birim=190.0, guncel_birim=180.0,
            maliyet_deger=950, guncel_deger=900, kar_zarar=-50, kar_zarar_pct=-5.3,
            para="USD", getiriler={},
        )
        kol = yonetici_pozisyon_kolonlari(p, pd_, tarama=tarama, fx=_fx())
        self.assertEqual(kol["Ekle"], "—")

    def test_tefas_ekle_stop_dort_hane(self):
        from portfoy_yoneticisi import _fmt_poz_birim

        fx = _fx()
        stop_s = _fmt_poz_birim(0.0285, "tefas", "PKT", "TL", fx, kaynak_pb="TL")
        self.assertIn("0.0285", stop_s)
        self.assertNotIn("0.03 TL", stop_s)

    def test_kur_risk_notu_eur_gosterim(self):
        from portfoy_yoneticisi import pozisyon_oneri_hucre

        h = pozisyon_oneri_hucre("Tut", "AL", 1.0, tur="hisse", gosterim_pb="EUR")
        self.assertIn("TL/EUR kuru", h["tip"])
        h2 = pozisyon_oneri_hucre("Kâr Al", "İZLE", 15.0, tur="hisse", gosterim_pb="EUR")
        self.assertIn("Kademeli realizasyon", h2["tip"])
        h3 = pozisyon_oneri_hucre("Tut", "AL", 1.0, tur="hisse", gosterim_pb="TL")
        self.assertNotIn("TL/EUR kuru", h3["tip"])


if __name__ == "__main__":
    unittest.main()
