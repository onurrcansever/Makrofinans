# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
import unittest.mock
from datetime import date

import pandas as pd

from varlik_fiyat import (
    PERIYOTLAR,
    _deger_tutar_bazli,
    _doviz_alim_kuru,
    _getiriler_portfoy,
    _gun_tutma,
    _legacy_tutar_modu,
    _miktar_maliyet_coz,
    _pb_cevir,
    pozisyon_legacy_normalize,
    portfoy_degerle,
)
from varliklarim import (
    VarlikPozisyon,
    VarlikPortfoy,
    VarlikStore,
    _hedef_aktarim_tutar,
    kaydet_store,
    oneri_portfoye_aktar,
    yukle_store,
    yeni_portfoy,
)
from birlesik_oneri import AracDagilimSatir, BirlesikOneri, HedefSatir
from decision_engine import PiyasaVerisi
from macro_data import MacroSnapshot


def _snap(eur_try=53.5, usd_try=57.8, altin_usd=3300.0):
    return MacroSnapshot(
        veri=PiyasaVerisi(eur_try=eur_try, usd_try=usd_try),
        altin_usd_oz=altin_usd,
        gumus_usd_oz=altin_usd / 80,
    )


class VarliklarimTest(unittest.TestCase):
    def test_pb_cevir(self):
        self.assertAlmostEqual(_pb_cevir(1000, "TL", "EUR", 50, 54), 20.0)
        self.assertAlmostEqual(_pb_cevir(100, "EUR", "TL", 50, 54), 5000.0)

    def test_bugun_getiri_sifir(self):
        seri = pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        bugun = date(2026, 1, 2)
        g = _getiriler_portfoy(seri, "2026-01-02", bugun)
        self.assertEqual(g["1G"], 0.0)
        self.assertEqual(g["1H"], 0.0)

    def test_tefas_tutar_bazli(self):
        self.assertAlmostEqual(_deger_tutar_bazli(716.0, 0.0), 716.0)
        self.assertAlmostEqual(_deger_tutar_bazli(716.0, 5.0), 716.0 * 1.05)

    def test_store_persist(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, ".varliklarim.json")
            import varliklarim as vm
            old = vm.STATE_PATH
            vm.STATE_PATH = path
            try:
                store = VarlikStore(
                    aktif_id="a",
                    portfoyler=[VarlikPortfoy(id="a", ad="Test", pozisyonlar=[
                        VarlikPozisyon(id="p1", tur="nakit_tl", miktar=1000, maliyet=1000, para_birimi="TL"),
                    ])],
                )
                kaydet_store(store)
                y2 = yukle_store()
                self.assertEqual(len(y2.portfoyler[0].pozisyonlar), 1)
                self.assertEqual(y2.portfoyler[0].pozisyonlar[0].miktar, 1000)
            finally:
                vm.STATE_PATH = old

    def test_yeni_portfoy(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, ".varliklarim.json")
            import varliklarim as vm
            old = vm.STATE_PATH
            vm.STATE_PATH = path
            try:
                store = VarlikStore(aktif_id="x", portfoyler=[VarlikPortfoy(id="x", ad="1")])
                p = yeni_portfoy(store, ad="Varlıklarım 2")
                self.assertEqual(p.ad, "Varlıklarım 2")
                self.assertEqual(len(store.portfoyler), 2)
            finally:
                vm.STATE_PATH = old

    def test_legacy_tutar_modu(self):
        p = VarlikPozisyon(
            id="x", tur="altin", miktar=170_000, maliyet=170_000, para_birimi="TL",
            alim_tarihi="2026-01-15",
        )
        self.assertTrue(_legacy_tutar_modu(p))

    def test_birimli_altin_kz(self):
        p = VarlikPozisyon(
            id="g1",
            tur="altin",
            miktar=50.0,
            alim_fiyati=3400.0,
            maliyet=170_000.0,
            para_birimi="TL",
            alim_tarihi="2026-01-15",
        )
        snap = _snap()
        portfoy = VarlikPortfoy(id="p", ad="T", pozisyonlar=[p])
        with unittest.mock.patch("varlik_fiyat._yf_indir", return_value=__import__("pandas").DataFrame()):
            deger = portfoy_degerle(portfoy, snap, normalize=False)
        pd_ = deger.pozisyonlar[0]
        self.assertAlmostEqual(pd_.maliyet_deger, 170_000.0)
        self.assertGreater(pd_.guncel_deger, 0)
        self.assertNotEqual(pd_.kar_zarar, 0.0)

    def test_miktar_maliyet_coz(self):
        p = VarlikPozisyon(
            id="t", tur="tefas", sembol="YIV", miktar=1000, alim_fiyati=5.0, maliyet=5000,
            para_birimi="TL",
        )
        qty, mal, alim = _miktar_maliyet_coz(p, None)
        self.assertEqual(qty, 1000)
        self.assertEqual(mal, 5000)
        self.assertEqual(alim, 5.0)

    def test_legacy_normalize(self):
        p = VarlikPozisyon(
            id="t", tur="tefas", sembol="YIV", miktar=5000, maliyet=5000, para_birimi="TL",
        )
        self.assertTrue(pozisyon_legacy_normalize(p, birim_alim=5.0))
        self.assertAlmostEqual(p.miktar, 1000.0)
        self.assertAlmostEqual(p.alim_fiyati, 5.0)

    def test_nakit_eur_alim_kuru_alim_tarihinden(self):
        p = VarlikPozisyon(
            id="e1",
            tur="nakit_eur",
            miktar=1000.0,
            maliyet=0.0,
            alim_fiyati=0.0,
            para_birimi="EUR",
            alim_tarihi="2025-03-01",
        )
        snap = _snap(eur_try=54.0)
        dates = pd.date_range("2025-01-01", periods=120, freq="D")
        fx = pd.Series([48.5] * (len(dates) - 1) + [54.0], index=dates)
        df = pd.DataFrame({
            "EURTRY=X": fx,
            "USDTRY=X": fx / 1.08,
            "GBPUSD=X": [1.34] * len(dates),
            "EURUSD=X": [1.08] * len(dates),
        }, index=dates)
        portfoy = VarlikPortfoy(id="p", ad="T", pozisyonlar=[p])
        with unittest.mock.patch("varlik_fiyat._yf_indir", return_value=df):
            deger = portfoy_degerle(portfoy, snap, normalize=False)
        pd_ = deger.pozisyonlar[0]
        self.assertAlmostEqual(pd_.alim_birim, 48.5)
        self.assertAlmostEqual(pd_.guncel_birim, 54.0)
        self.assertAlmostEqual(pd_.maliyet_deger, 48_500.0)
        self.assertAlmostEqual(pd_.guncel_deger, 54_000.0)
        self.assertAlmostEqual(pd_.kar_zarar, 5_500.0)

    def test_nakit_ron_alim_kuru_tl_gosterim(self):
        p = VarlikPozisyon(
            id="r1",
            tur="nakit_ron",
            miktar=7914.98,
            maliyet=0.0,
            alim_fiyati=0.0,
            para_birimi="RON",
            alim_tarihi="2026-07-13",
        )
        snap = _snap(eur_try=53.04, usd_try=57.0)
        dates = pd.date_range("2026-01-01", periods=200, freq="D")
        eur_try_s = pd.Series([52.0] * len(dates), index=dates)
        eur_ron_s = pd.Series([5.10] * len(dates), index=dates)
        df = pd.DataFrame(
            {
                ("EURTRY=X", "Close"): eur_try_s,
                ("EURRON=X", "Close"): eur_ron_s,
            }
        )
        portfoy = VarlikPortfoy(id="p", ad="T", pozisyonlar=[p])
        with unittest.mock.patch("varlik_fiyat._yf_indir", return_value=df):
            deger = portfoy_degerle(portfoy, snap, normalize=False)
        pd_ = deger.pozisyonlar[0]
        self.assertAlmostEqual(pd_.alim_birim, 52.0 / 5.10, places=2)
        self.assertAlmostEqual(pd_.guncel_birim, 52.0 / 5.10, places=2)
        self.assertAlmostEqual(pd_.maliyet_deger, 7914.98 * (52.0 / 5.10), delta=5.0)
        from fiyat_para import kaynak_para_birimi, pb_cevir
        birim_pb = kaynak_para_birimi("", pozisyon_turu="nakit_ron", varlik_turu="nakit_ron")
        self.assertEqual(birim_pb, "TL")
        alis_tl = pb_cevir(pd_.alim_birim, birim_pb, "TL", 53.04, 57.0)
        self.assertLess(alis_tl, 15.0)
        self.assertGreater(alis_tl, 8.0)

    def test_nakit_eur_guncel_kur_alis_olarak_kullanilmaz(self):
        p = VarlikPozisyon(
            id="e2",
            tur="nakit_eur",
            miktar=1000.0,
            maliyet=50_000.0,
            alim_fiyati=0.0,
            para_birimi="EUR",
            alim_tarihi="2025-03-01",
        )
        snap = _snap(eur_try=54.0)
        portfoy = VarlikPortfoy(id="p", ad="T", pozisyonlar=[p])
        with unittest.mock.patch("varlik_fiyat._yf_indir", return_value=pd.DataFrame()):
            deger = portfoy_degerle(portfoy, snap, normalize=False)
        pd_ = deger.pozisyonlar[0]
        self.assertAlmostEqual(pd_.alim_birim, 50.0)
        self.assertAlmostEqual(pd_.guncel_birim, 54.0)
        self.assertNotEqual(pd_.alim_birim, pd_.guncel_birim)

    def test_doviz_alim_kuru_oncelik(self):
        p = VarlikPozisyon(
            id="e3", tur="nakit_eur", miktar=100.0, maliyet=5200.0,
            alim_fiyati=51.0, para_birimi="EUR", alim_tarihi="2025-03-01",
        )
        fx = pd.Series([48.5], index=pd.to_datetime(["2025-03-01"]))
        self.assertAlmostEqual(_doviz_alim_kuru(p, fx, 100.0, 5200.0), 51.0)

    def test_hedef_aktarim_cift_sayim_onleme(self):
        h = HedefSatir("TL vadeli mevduat", "banka", 22.0, 220_000.0, "TL")
        tutar = _hedef_aktarim_tutar(h, tefas_toplam=77_000.0, etf_toplam=0.0, etf_kaynak="EUR")
        self.assertAlmostEqual(tutar, 143_000.0)

    def test_oneri_aktar_toplam_portfoy(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, ".varliklarim.json")
            import varliklarim as vm
            old = vm.STATE_PATH
            vm.STATE_PATH = path
            try:
                self._oneri_aktar_toplam_portfoy_impl()
            finally:
                vm.STATE_PATH = old

    def _oneri_aktar_toplam_portfoy_impl(self):
        oneri = BirlesikOneri(
            hedef_tablo=[
                HedefSatir("TL vadeli mevduat", "banka", 22.0, 220_000.0, "TL"),
                HedefSatir("EUR nakit / mevduat", "eur", 35.0, 350_000.0, "TL"),
                HedefSatir("USD nakit / mevduat", "usd", 19.0, 190_000.0, "TL"),
                HedefSatir("Altın", "altin", 17.0, 170_000.0, "TL"),
                HedefSatir("Gümüş", "gumus", 3.0, 30_000.0, "TL"),
                HedefSatir("BIST 100 (hisse)", "detay", 4.0, 40_000.0, "TL"),
                HedefSatir("TEFAS fon", "detay", 7.7, 77_000.0, "TL"),
                HedefSatir("ETF (hisse senedi)", "detay", 15.8, 158_000.0, "TL"),
            ],
            arac_dagilim=[
                AracDagilimSatir("TEFAS fon", "YIV", "fon", 7.7, 37.0, 28_490.0, "TL"),
                AracDagilimSatir("TEFAS fon", "YAY", "fon", 7.7, 32.0, 24_640.0, "TL"),
                AracDagilimSatir("TEFAS fon", "YTD", "fon", 7.7, 31.0, 23_870.0, "TL"),
                AracDagilimSatir("ETF (hisse senedi)", "CSPX", "etf", 15.8, 55.0, 86_900.0, "TL"),
                AracDagilimSatir("ETF (hisse senedi)", "VUAA", "etf", 15.8, 45.0, 71_100.0, "TL"),
                AracDagilimSatir("BIST 100 (hisse)", "EKGYO", "gyo", 4.0, 35.0, 14_000.0, "TL"),
                AracDagilimSatir("BIST 100 (hisse)", "ISCTR", "bank", 4.0, 33.0, 13_200.0, "TL"),
                AracDagilimSatir("BIST 100 (hisse)", "YKBNK", "bank", 4.0, 32.0, 12_800.0, "TL"),
            ],
        )
        store = VarlikStore(
            aktif_id="p1",
            portfoyler=[VarlikPortfoy(id="p1", ad="Deneme")],
        )
        n = oneri_portfoye_aktar(store, "p1", oneri, para_birimi="TL")
        self.assertGreater(n, 0)
        toplam = sum(p.maliyet for p in store.portfoyler[0].pozisyonlar)
        self.assertAlmostEqual(toplam, 1_000_000.0, delta=1.0)
        self.assertEqual(store.portfoyler[0].ad, "Deneme")


if __name__ == "__main__":
    unittest.main()
