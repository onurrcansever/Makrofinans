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
    pozisyon_canli_fiyat,
    pozisyon_emtia_fiyat,
    pozisyon_evren_listesi,
    pozisyon_sembol_normalize,
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

    def test_evren_arama_kod_oncelikli(self):
        # "KLU" araması, adında "ÇOKLU" geçen fon yerine kodu KLU olanı öne almalı.
        from types import SimpleNamespace

        fonlar = [
            SimpleNamespace(kod="CKL", kisa_ad="ÇOKLU VARLIK DEĞİŞKEN", ad="ÇOKLU VARLIK DEĞİŞKEN FON", para_birimi="TL"),
            SimpleNamespace(kod="KLU", kisa_ad="PARA PİYASASI KATILIM", ad="PARA PİYASASI KATILIM (TL) FONU", para_birimi="TL"),
        ]
        res = pozisyon_evren_listesi("tefas", tefas_fonlar=fonlar, ara="KLU")
        self.assertTrue(res)
        self.assertEqual(res[0].sembol, "KLU")
        self.assertIn("KLU", [x.sembol for x in res])

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

    def test_yukle_store_ci_sync_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            import varliklarim as vm
            old_state = vm.STATE_PATH
            old_ci = vm.CI_SYNC_PATH
            vm.STATE_PATH = os.path.join(td, "missing.json")
            ci_path = os.path.join(td, "data", "ci_varliklarim.json")
            os.makedirs(os.path.dirname(ci_path), exist_ok=True)
            vm.CI_SYNC_PATH = ci_path
            try:
                store = VarlikStore(
                    aktif_id="a",
                    portfoyler=[VarlikPortfoy(id="a", ad="CI", pozisyonlar=[
                        VarlikPozisyon(id="p1", tur="nakit_eur", miktar=500, maliyet=500, para_birimi="EUR"),
                    ])],
                )
                kaydet_store(store)
                with open(ci_path, "w", encoding="utf-8") as f:
                    import json
                    json.dump({
                        "aktif_id": "a",
                        "portfoyler": [{
                            "id": "a",
                            "ad": "CI",
                            "pozisyonlar": [{
                                "id": "p1", "tur": "nakit_eur", "miktar": 500,
                                "maliyet": 500, "para_birimi": "EUR", "alim_fiyati": 0.0,
                            }],
                        }],
                    }, f)
                y2 = yukle_store()
                self.assertEqual(y2.portfoyler[0].pozisyonlar[0].miktar, 500)
            finally:
                vm.STATE_PATH = old_state
                vm.CI_SYNC_PATH = old_ci

    def test_yukle_store_ci_oncelik_github_actions(self):
        with tempfile.TemporaryDirectory() as td:
            import varliklarim as vm
            old_state = vm.STATE_PATH
            old_ci = vm.CI_SYNC_PATH
            state_path = os.path.join(td, ".varliklarim.json")
            ci_path = os.path.join(td, "data", "ci_varliklarim.json")
            os.makedirs(os.path.dirname(ci_path), exist_ok=True)
            vm.STATE_PATH = state_path
            vm.CI_SYNC_PATH = ci_path
            try:
                with open(state_path, "w", encoding="utf-8") as f:
                    import json
                    json.dump({"aktif_id": "x", "portfoyler": []}, f)
                with open(ci_path, "w", encoding="utf-8") as f:
                    import json
                    json.dump({
                        "aktif_id": "a",
                        "portfoyler": [{
                            "id": "a", "ad": "CI", "pozisyonlar": [{
                                "id": "p1", "tur": "nakit_tl", "miktar": 1000,
                                "maliyet": 1000, "para_birimi": "TL", "alim_fiyati": 0.0,
                            }],
                        }],
                    }, f)
                with unittest.mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
                    y2 = yukle_store()
                self.assertEqual(len(y2.portfoyler[0].pozisyonlar), 1)
            finally:
                vm.STATE_PATH = old_state
                vm.CI_SYNC_PATH = old_ci

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


class PozisyonEklemeHelperTest(unittest.TestCase):
    def test_bist_sembol_normalize(self):
        self.assertEqual(pozisyon_sembol_normalize("hisse", "thyao"), "THYAO.IS")
        self.assertEqual(pozisyon_sembol_normalize("hisse", "THYAO.IS"), "THYAO.IS")

    def test_etf_sembol_normalize(self):
        sym = pozisyon_sembol_normalize("etf", "CSPX")
        self.assertTrue(sym.endswith(".L") or "CSPX" in sym.upper())

    def test_evren_listesi_hisse_filtre(self):
        liste = pozisyon_evren_listesi("hisse", ara="THYAO")
        self.assertTrue(any("THYAO" in x.sembol for x in liste))
        self.assertTrue(all(".IS" in x.sembol for x in liste))

    def test_evren_listesi_etf(self):
        liste = pozisyon_evren_listesi("etf", ara="CSPX")
        self.assertTrue(len(liste) >= 1)
        self.assertIn("CSPX", liste[0].label.upper())

    def test_canli_fiyat_tarama_oncelik(self):
        class _H:
            sembol = "THYAO.IS"
            fiyat = 312.5

        class _T:
            hisseler = [_H()]

        px, pb = pozisyon_canli_fiyat("THYAO", "hisse", _T())
        self.assertAlmostEqual(px, 312.5)
        self.assertEqual(pb, "TL")

    def test_evren_listesi_hisse_us(self):
        liste = pozisyon_evren_listesi("hisse_us", ara="NVDA")
        self.assertTrue(len(liste) >= 1)
        self.assertTrue(all("NASDAQ" in x.label or "SP500" in x.label for x in liste))

    def test_emtia_fiyat(self):
        snap = _snap()
        px, pb = pozisyon_emtia_fiyat("altin", snap)
        self.assertIsNotNone(px)
        self.assertGreater(px, 0)
        self.assertEqual(pb, "TL")

    def test_hisse_us_normalize(self):
        self.assertEqual(pozisyon_sembol_normalize("hisse_us", "NVDA"), "NVDA")

    def test_pozisyon_tutma_gun_bugun(self):
        from varlik_fiyat import pozisyon_tutma_gun
        from datetime import date

        self.assertEqual(pozisyon_tutma_gun(date.today().isoformat(), date.today()), 0)

    def test_tablo_getiri_sifir_tutma(self):
        from varliklarim_ui import _pozisyon_tablo_getiri
        import pandas as pd

        idx = pd.date_range("2026-01-01", periods=40, freq="D")
        usd = pd.Series([35.0 + i * 0.01 for i in range(40)], index=idx)
        eur = pd.Series([38.0 + i * 0.01 for i in range(40)], index=idx)
        out = _pozisyon_tablo_getiri(
            0.0, "TL", 30, eur, usd,
            asset_pb="USD", varlik_turu="hisse_us", tutma_gun=0,
        )
        self.assertEqual(out, 0.0)

        class _F:
            kod = "YIV"
            fiyat = 12.34
            para_birimi = "TL"

        px, pb = pozisyon_canli_fiyat("YIV", "tefas", None, tefas_fonlar=[_F()])
        self.assertAlmostEqual(px, 12.34)
        self.assertEqual(pb, "TL")


if __name__ == "__main__":
    unittest.main()
