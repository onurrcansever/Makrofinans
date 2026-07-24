# -*- coding: utf-8 -*-
"""TEFAS fon modülü testleri."""
import unittest
from unittest.mock import patch

from investor_profile import YatirimProfili
from tefas_skor import fonlari_skorla, top_oneri, _ONERI_AL
from tefas_universe import (
    fon_kategorisi,
    fon_para_birimi,
    kisa_fon_adi,
    kt_fon_mu,
    portfoy_sirketi,
    yk_fon_mu,
)
from tefas_data import FonPerformans, TefasTaramaSonuc, _getiri_hesapla
import pandas as pd


class TefasUniverseTest(unittest.TestCase):
    def test_yk_tespit(self):
        self.assertTrue(yk_fon_mu("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"))
        self.assertTrue(yk_fon_mu("KUVEYT TÜRK PORTFÖY PARA PİYASASI KATILIM (TL) FONU"))
        self.assertTrue(kt_fon_mu("KUVEYT TÜRK PORTFÖY ALTIN KATILIM FONU"))
        self.assertFalse(yk_fon_mu("AK PORTFÖY"))
        self.assertFalse(kt_fon_mu("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"))

    def test_kategori_pp(self):
        ad = "YAPI KREDİ PORTFÖY PARA PİYASASI FONU"
        self.assertEqual(fon_kategorisi(ad), "para_piyasasi")
        self.assertEqual(
            fon_kategorisi("KUVEYT TÜRK PORTFÖY PARA PİYASASI KATILIM (TL) FONU"),
            "para_piyasasi",
        )
        self.assertEqual(
            fon_kategorisi("KUVEYT TÜRK PORTFÖY KATILIM HİSSE SENEDİ (TL) FONU"),
            "hisse",
        )

    def test_kisa_ad(self):
        self.assertIn("PARA", kisa_fon_adi("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"))
        self.assertNotIn("KUVEYT", kisa_fon_adi("KUVEYT TÜRK PORTFÖY PARA PİYASASI KATILIM FONU"))
        self.assertIn("PARA", kisa_fon_adi("KUVEYT TÜRK PORTFÖY PARA PİYASASI KATILIM FONU"))

    def test_portfoy_sirketi(self):
        self.assertEqual(portfoy_sirketi("YAPI KREDİ PORTFÖY PARA PİYASASI FONU"), "Yapı Kredi")
        self.assertEqual(portfoy_sirketi("KUVEYT TÜRK PORTFÖY ALTIN KATILIM FONU"), "Kuveyt Türk")
        self.assertEqual(portfoy_sirketi("AK PORTFÖY ALTIN FONU"), "Diğer")

    def test_para_birimi(self):
        self.assertEqual(fon_para_birimi("SERBEST (DÖVİZ-AVRO) FON"), "EUR")
        self.assertEqual(fon_para_birimi("AKATLAR SERBEST (DÖVİZ) ÖZEL FON"), "USD")
        self.assertEqual(fon_para_birimi("ABC EUR FON"), "EUR")
        self.assertEqual(fon_para_birimi("XYZ EURO BONO FONU"), "EUR")
        # EUROBOND içinde EURO geçse de ayrı token değil → döviz/USD yolu veya KARISIK
        self.assertNotEqual(fon_para_birimi("EUROBOND BORÇLANMA FONU"), "EUR")

    def test_tefas_fiyat_tl_den_eur(self):
        from fiyat_para import tefas_tablo_fiyat

        v = tefas_tablo_fiyat(2.1019, "EUR", "TL", 38.0, 41.0)
        self.assertAlmostEqual(v, 2.1019 / 38.0, places=4)

    def test_tefas_usd_fon_eur_display(self):
        from fiyat_para import tefas_tablo_fiyat

        # 10 USD @ EURUSD=1.08 → 10/1.08 EUR (USD köprüsü)
        v = tefas_tablo_fiyat(10.0, "EUR", "USD", 38.0, 41.0, eur_usd=1.08)
        self.assertAlmostEqual(v, 10.0 / 1.08, places=2)

    def test_tefas_karisik_no_silent_tl(self):
        from fiyat_para import tefas_tablo_fiyat

        self.assertIsNone(tefas_tablo_fiyat(1.5, "EUR", "KARISIK", 38.0, 41.0))


class TefasSkorTest(unittest.TestCase):
    def test_skor_sirala(self):
        f1 = FonPerformans(
            kod="YLB", ad="x", kisa_ad="PP", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_3a=5.0,
        )
        f2 = FonPerformans(
            kod="YHS", ad="y", kisa_ad="Hisse", kategori="hisse",
            kategori_etiket="Hisse", para_birimi="TL", para_etiket="TL",
            fiyat=25.0, getiri_3a=15.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[f1, f2]),
            YatirimProfili(risk="dusuk", vade="kisa_6"),
            rejim="TL_FIRSAT",
            mevduat_reel=2.0,
        )
        self.assertEqual(sonuc.fonlar[0].kod, "YLB")

    def test_kisa_3_degisken_geride(self):
        pp = FonPerformans(
            kod="PKT", ad="pp", kisa_ad="PP", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_1a=4.0,
        )
        deg = FonPerformans(
            kod="YAK", ad="y", kisa_ad="Deg", kategori="degisken",
            kategori_etiket="Deg", para_birimi="TL", para_etiket="TL",
            fiyat=10.0, getiri_1a=12.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[deg, pp]),
            YatirimProfili(risk="orta", vade="kisa_3"),
            rejim="TL_FIRSAT",
        )
        self.assertEqual(sonuc.fonlar[0].kod, "PKT")
        aday = top_oneri(sonuc, n=2, kategoriler=("para_piyasasi", "borclanma", "katilim"))
        self.assertTrue(aday)
        self.assertEqual(aday[0].kategori, "para_piyasasi")

    def test_oneri_dagilimi_signal_engine_esikleri(self):
        """Benzer para piyasası fonları AL/İZLE/BEKLE/Zayıf olarak ayrışmalı."""
        fonlar = []
        for i, (kod, g1a, buyuk) in enumerate([
            ("YLB", 4.5, 6e9),
            ("PKT", 4.2, 3e9),
            ("YIV", 3.8, 1.5e9),
            ("YHS", 3.2, 8e8),
            ("YAK", 2.5, 5e7),
            ("YDE", 1.8, 2e7),
        ]):
            fonlar.append(
                FonPerformans(
                    kod=kod,
                    ad=f"fon {kod}",
                    kisa_ad=kod,
                    kategori="para_piyasasi" if kod != "YAK" else "degisken",
                    kategori_etiket="PP",
                    para_birimi="TL",
                    para_etiket="TL",
                    fiyat=1.7 + i * 0.01,
                    getiri_1a=g1a,
                    getiri_3a=g1a,
                    fon_buyuklugu=buyuk,
                )
            )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=fonlar),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            rejim="TL_FIRSAT",
        )
        etiketler = {f.oneri for f in sonuc.fonlar}
        self.assertIn("AL", etiketler)
        self.assertTrue(len(etiketler) >= 2)
        self.assertLess(sum(1 for f in sonuc.fonlar if f.oneri == "AL"), len(sonuc.fonlar))
        self.assertGreaterEqual(sonuc.fonlar[0].skor, _ONERI_AL)
        al = top_oneri(sonuc, n=3)
        self.assertTrue(all(f.oneri in ("AL", "IZLE") for f in al))

    def test_kategori_filtresi_skorlari_korur(self):
        """Filtre yalnızca listeler — skorları yeniden yüzdeliklemez."""
        pp = FonPerformans(
            kod="A", ad="a", kisa_ad="A", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_1a=4.0, fon_buyuklugu=5e9,
        )
        pp2 = FonPerformans(
            kod="B", ad="b", kisa_ad="B", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.8, getiri_1a=3.5, fon_buyuklugu=1e9,
        )
        hisse = FonPerformans(
            kod="C", ad="c", kisa_ad="C", kategori="hisse",
            kategori_etiket="Hisse", para_birimi="TL", para_etiket="TL",
            fiyat=10.0, getiri_1a=12.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[pp, pp2, hisse]),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            rejim="NOTR",
        )
        skor_a = next(f for f in sonuc.fonlar if f.kod == "A").skor
        sadece_pp = [f for f in sonuc.fonlar if f.kategori == "para_piyasasi"]
        self.assertEqual(next(f for f in sadece_pp if f.kod == "A").skor, skor_a)
        self.assertNotEqual(sadece_pp[0].skor, 100.0)


class TefasGetiriTest(unittest.TestCase):
    def test_getiri_hesap(self):
        df = pd.DataFrame({
            "date_dt": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "price": [100.0, 105.0, 110.0],
        })
        g = _getiri_hesapla(df, 30)
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g, 10.0, delta=0.5)

    def test_kisa_tarihce_3a_ybb_none(self):
        """30 günlük seride 90g/YBB uydurma eşitleme yapmaz (ekran bug'ı)."""
        from tefas_data import _ybb_getiri

        son = pd.Timestamp("2026-07-20")
        dates = pd.date_range(son - pd.Timedelta(days=29), son, freq="D")
        df = pd.DataFrame({"date_dt": dates, "price": [100.0 + i * 0.1 for i in range(len(dates))]})
        self.assertIsNotNone(_getiri_hesapla(df, 7))
        self.assertIsNotNone(_getiri_hesapla(df, 30))
        self.assertIsNone(_getiri_hesapla(df, 90))
        self.assertIsNone(_ybb_getiri(df))

    def test_tam_ybb(self):
        from tefas_data import _ybb_getiri

        dates = pd.date_range("2026-01-02", "2026-07-20", freq="D")
        df = pd.DataFrame({
            "date_dt": dates,
            "price": [100.0 + i * 0.05 for i in range(len(dates))],
        })
        g = _ybb_getiri(df)
        self.assertIsNotNone(g)
        self.assertGreater(g, 0)


class TefasPencereYetersizTest(unittest.TestCase):
    """Kesik pencere tespiti — 3A/YBB toplu boşsa tam pencereye yükseltilmeli."""

    def _sonuc(self, ybb_dolu: bool, n: int = 20):
        from types import SimpleNamespace

        fonlar = [
            SimpleNamespace(
                kod=str(i),
                getiri_1a=1.0,
                getiri_3a=2.0,
                getiri_ybb=(5.0 if ybb_dolu else None),
            )
            for i in range(n)
        ]
        return SimpleNamespace(fonlar=fonlar)

    def test_kisa_pencere_yetersiz(self):
        from app_veri import _tefas_pencere_yetersiz_mu

        self.assertTrue(_tefas_pencere_yetersiz_mu(self._sonuc(ybb_dolu=False)))

    def test_tam_pencere_yeterli(self):
        from app_veri import _tefas_pencere_yetersiz_mu

        self.assertFalse(_tefas_pencere_yetersiz_mu(self._sonuc(ybb_dolu=True)))

    def test_az_fon_guard(self):
        from app_veri import _tefas_pencere_yetersiz_mu

        self.assertFalse(_tefas_pencere_yetersiz_mu(self._sonuc(ybb_dolu=False, n=3)))


if __name__ == "__main__":
    unittest.main()
