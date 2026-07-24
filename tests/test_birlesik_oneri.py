# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from allocation_engine import tahsis_hesapla
from birlesik_oneri import birlesik_oneri_olustur, _bist_payini_dagit, _skorla_bol
from investor_profile import YatirimProfili
from kullanici_portfoy import KullaniciPortfoy, MevcutPozisyon
from macro_data import demo_snapshot
from tefas_data import FonPerformans, TefasTaramaSonuc


class BirlesikOneriTest(unittest.TestCase):
    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_mevduat_tut_onerisi(self, mock_yk):
        mock_yk.return_value = TefasTaramaSonuc(hata="skip")
        snap = demo_snapshot()
        profil = YatirimProfili(risk="dusuk", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(
            para_birimi="TL",
            toplam=1_050_000.0,
            pozisyonlar=[
                MevcutPozisyon(
                    tur="tl_mevduat",
                    tutar=1_050_000.0,
                    para_birimi="TL",
                    banka="Yapı Kredi",
                    vade_gun=90,
                    brut_faiz=42.0,
                )
            ],
        )
        oneri = birlesik_oneri_olustur(
            snap, tahsis, profil, kp, mevduat_reel=1.0, tarama=None,
        )
        self.assertTrue(oneri.mevcut_notlar)
        self.assertIn("Yapı Kredi", oneri.mevcut_notlar[0])
        self.assertTrue(oneri.grafik_hedef)
        tl_etiket = oneri.grafik_hedef.keys().__iter__().__next__()
        self.assertIsNotNone(tl_etiket)

    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_tefas_istek_kapali_ag_cagirmaz(self, mock_yk):
        snap = demo_snapshot()
        profil = YatirimProfili(risk="dusuk", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(para_birimi="EUR", toplam=30000.0)
        oneri = birlesik_oneri_olustur(
            snap, tahsis, profil, kp, mevduat_reel=2.0, tefas_istek=False,
        )
        mock_yk.assert_not_called()
        self.assertTrue(oneri.hedef_tablo)
        tefas_d = [s for s in oneri.arac_dagilim if s.ust_kategori == "TEFAS fon"]
        self.assertEqual(tefas_d, [])

    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_kisa_vade_etf_kapali(self, mock_yk):
        mock_yk.return_value = TefasTaramaSonuc(hata="skip")
        snap = demo_snapshot()
        profil = YatirimProfili(risk="orta", vade="kisa_3")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(para_birimi="EUR", toplam=30000.0)
        oneri = birlesik_oneri_olustur(snap, tahsis, profil, kp, mevduat_reel=2.0)
        etf_d = [s for s in oneri.arac_dagilim if "ETF" in s.ust_kategori]
        self.assertEqual(etf_d, [])
        self.assertTrue(any("ETF" in n for n in oneri.mevcut_notlar))

    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_tefas_vade_onerisi(self, mock_yk):
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
                    dagilim_ozet="Bono/Repo %60",
                    etkin_kategori="borclanma",
                )
            ]
        )
        snap = demo_snapshot()
        profil = YatirimProfili(risk="dusuk", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(para_birimi="EUR", toplam=30000.0)
        oneri = birlesik_oneri_olustur(snap, tahsis, profil, kp, mevduat_reel=2.0)
        tefas = [o for o in oneri.vade if o.sinif == "tefas"]
        self.assertTrue(tefas)
        self.assertIn("YLB", tefas[0].baslik)
        self.assertTrue(oneri.hedef_tablo)
        tl_satir = [h for h in oneri.hedef_tablo if h.kategori == "TL vadeli mevduat"]
        tefas_satir = [h for h in oneri.hedef_tablo if h.kategori == "TEFAS fon"]
        self.assertTrue(tefas_satir)
        self.assertIn("YLB", tefas_satir[0].arac)
        # TEFAS tl_deposit içinden — makro TL + TEFAS ≈ orijinal tl (çift sayım yok)
        tl_w = tahsis.agirliklar.get("tl_deposit", 0) * 100
        tl_pct = tl_satir[0].agirlik_pct if tl_satir else 0.0
        self.assertAlmostEqual(tl_pct + tefas_satir[0].agirlik_pct, tl_w, delta=1.5)
        self.assertAlmostEqual(
            sum(h.agirlik_pct for h in oneri.hedef_tablo), 100.0, delta=1.5,
        )
        tefas_d = [s for s in oneri.arac_dagilim if s.ust_kategori == "TEFAS fon"]
        self.assertTrue(tefas_d)
        self.assertAlmostEqual(sum(s.kategori_ici_pct for s in tefas_d), 100.0, delta=0.2)

    def test_skorla_bol_toplam(self):
        satirlar = _skorla_bol(
            [("THYAO", "THY", 60, "UYGUN"), ("GARAN", "Garanti", 40, "SINIRLI")],
            kategori_tutar_eur=1000.0,
            kategori_portfoy_pct=3.3,
            pb="EUR",
            eur_try=35.0,
            ust_kategori="BIST 100 (hisse)",
        )
        self.assertEqual(len(satirlar), 2)
        self.assertAlmostEqual(sum(s.kategori_ici_pct for s in satirlar), 100.0, delta=0.2)
        self.assertAlmostEqual(sum(s.portfoy_pct for s in satirlar), 3.3, delta=0.05)
        self.assertGreater(satirlar[0].tutar, satirlar[1].tutar)

    def test_bist_payini_dagit(self):
        src = {
            "tl_deposit": 0.22,
            "eur_cash": 0.28,
            "usd_cash": 0.18,
            "gold": 0.18,
            "silver": 0.08,
            "bist": 0.06,
            "crypto": 0.0,
        }
        out = _bist_payini_dagit(src)
        self.assertAlmostEqual(out.get("bist", 1), 0.0, places=4)
        self.assertAlmostEqual(sum(out.values()), sum(src.values()), places=4)

    @patch("birlesik_oneri.yk_fonlari_performans")
    def test_bist_adayi_yoksa_makro_dusurulur(self, mock_yk):
        from unittest.mock import MagicMock
        from stock_scanner import HisseAnaliz, TaramaSonucu

        mock_yk.return_value = TefasTaramaSonuc(hata="skip")
        snap = demo_snapshot()
        profil = YatirimProfili(risk="orta", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        kp = KullaniciPortfoy(para_birimi="TL", toplam=1_000_000.0)
        bist_w = tahsis.agirliklar.get("bist", 0)
        self.assertGreaterEqual(bist_w, 0.03)

        h = HisseAnaliz(
            "DOAS.IS", "DOAS", "BIST", 180.0, 0, -4, 3, -5, 42, 185, 180,
            "BEKLE", 89, "test", "tuketim", teknik_skor=75, temel_skor=98,
            bilesik_skor=89, alim_uygun="SINIRLI",
        )
        tarama = TaramaSonucu(hisseler=[h], makro_rejim=tahsis.rejim.rejim)
        oneri = birlesik_oneri_olustur(
            snap, tahsis, profil, kp, tarama=tarama, tefas_istek=False,
        )
        kategoriler = [r.kategori for r in oneri.hedef_tablo]
        self.assertNotIn("BIST 100 (hisse)", kategoriler)
        self.assertTrue(any("yeniden dağıtıldı" in n for n in oneri.mevcut_notlar))
        self.assertAlmostEqual(sum(oneri.grafik_hedef.values()), 100.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
