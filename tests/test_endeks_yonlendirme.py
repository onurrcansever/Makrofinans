# -*- coding: utf-8 -*-
"""Endeks platform yönlendirme — hisse/_sinyal_uret’ten bağımsız."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from endeks_yonlendirme import (
    KURULUM_TREND_CEKILME,
    KURULUM_ZAYIF,
    karar,
    oncelik_ozeti,
    platform_for,
)


class PlatformTest(unittest.TestCase):
    def test_platform_tr_abd(self):
        self.assertEqual(platform_for("XU100.IS"), "TR")
        self.assertEqual(platform_for("^NDX"), "ABD")
        self.assertEqual(platform_for("^GSPC"), "ABD")


class KararTest(unittest.TestCase):
    def test_bist_zayif_momentum_no_artir(self):
        """Ekrandaki BIST benzeri: RSI ~44, 1A/3A eksi, düşen SMA → Artır yok."""
        k = karar(
            sembol="XU100.IS",
            fiyat=259.0,
            rsi=43.7,
            sma20=265.0,
            sma50=270.0,
            sma200=280.0,
            degisim_1ay=-3.16,
            degisim_3ay=-4.18,
            fx_ok=True,
        )
        self.assertEqual(k.platform, "TR")
        self.assertEqual(k.kurulum, KURULUM_ZAYIF)
        self.assertNotEqual(k.aksiyon, "ARTIR")
        self.assertIn(k.aksiyon, ("BEKLE", "AZALT"))

    def test_ndx_pullback_positive_3a(self):
        """NASDAQ 100: RSI dip + pozitif 3A + trend SMA → Artır veya Koru."""
        k = karar(
            sembol="^NDX",
            fiyat=24975.0,
            rsi=41.8,
            sma20=25200.0,
            sma50=24800.0,
            sma200=22000.0,
            degisim_1ay=-3.37,
            degisim_3ay=12.02,
            fx_ok=True,
        )
        self.assertEqual(k.platform, "ABD")
        self.assertEqual(k.kurulum, KURULUM_TREND_CEKILME)
        self.assertIn(k.aksiyon, ("ARTIR", "KORU"))

    def test_fx_yok_artir_downgrade(self):
        k_ok = karar(
            sembol="^GSPC",
            fiyat=6500.0,
            rsi=44.0,
            sma20=6550.0,
            sma50=6400.0,
            sma200=6000.0,
            degisim_1ay=-1.0,
            degisim_3ay=9.0,
            fx_ok=True,
        )
        k_fx = karar(
            sembol="^GSPC",
            fiyat=6500.0,
            rsi=44.0,
            sma20=6550.0,
            sma50=6400.0,
            sma200=6000.0,
            degisim_1ay=-1.0,
            degisim_3ay=9.0,
            fx_ok=False,
        )
        self.assertEqual(k_ok.aksiyon, "ARTIR")
        self.assertNotEqual(k_fx.aksiyon, "ARTIR")
        self.assertLessEqual(k_fx.guven, 40.0)

    def test_asiri_isinma_azalt(self):
        k = karar(
            sembol="^IXIC",
            fiyat=22000.0,
            rsi=78.0,
            sma20=21500.0,
            sma50=21000.0,
            degisim_1ay=5.0,
            degisim_3ay=15.0,
            fx_ok=True,
        )
        self.assertEqual(k.aksiyon, "AZALT")
        self.assertEqual(k.sinyal, "ASIRI_ALIM")

    def test_legacy_sinyal_not_alim_firsati(self):
        """Endeks legacy map ALIM_FIRSATI üretmez (hisse etiketinden ayrışma)."""
        k = karar(
            sembol="^NDX",
            fiyat=25000.0,
            rsi=40.0,
            sma20=25200.0,
            sma50=24800.0,
            sma200=22000.0,
            degisim_1ay=-2.0,
            degisim_3ay=10.0,
            fx_ok=True,
        )
        self.assertNotEqual(k.sinyal, "ALIM_FIRSATI")


class OncelikTest(unittest.TestCase):
    def test_abd_oncelik(self):
        rows = [
            SimpleNamespace(
                platform="TR", ad="BIST 100", sembol="XU100.IS",
                aksiyon="BEKLE", degisim_3ay=-4.0,
            ),
            SimpleNamespace(
                platform="ABD", ad="NASDAQ 100", sembol="^NDX",
                aksiyon="ARTIR", degisim_3ay=12.0,
            ),
            SimpleNamespace(
                platform="ABD", ad="S&P 500", sembol="^GSPC",
                aksiyon="KORU", degisim_3ay=9.0,
            ),
        ]
        text = oncelik_ozeti(rows)
        self.assertIn("Bugün öncelik", text)
        self.assertIn("ABD", text)
        self.assertIn("BIST", text)

    def test_bist_oncelik(self):
        rows = [
            SimpleNamespace(
                platform="TR", ad="BIST 100", sembol="XU100.IS",
                aksiyon="ARTIR", degisim_3ay=10.0,
            ),
            SimpleNamespace(
                platform="ABD", ad="S&P 500", sembol="^GSPC",
                aksiyon="BEKLE", degisim_3ay=-2.0,
            ),
        ]
        text = oncelik_ozeti(rows)
        self.assertIn("BIST", text)
        self.assertIn("ABD", text)


class IsolationFromHisseTest(unittest.TestCase):
    """Hisse _sinyal_uret hâlâ ALIM_FIRSATI üretebilir — endeks modülü dokunmaz."""

    def test_sinyal_uret_unchanged(self):
        from stock_scanner import _sinyal_uret

        sinyal, skor, _ = _sinyal_uret(
            100.0, 40.0, 101.0, 99.0, degisim_3ay=5.0, degisim_1ay=-1.0,
        )
        self.assertEqual(sinyal, "ALIM_FIRSATI")
        self.assertGreaterEqual(skor, 55)


class StaleCacheEnrichTest(unittest.TestCase):
    def test_doldur_eski_endeks(self):
        from endeks_yonlendirme import endeks_alanlarini_doldur

        e = SimpleNamespace(
            ad="NASDAQ 100",
            sembol="^NDX",
            fiyat=24981.0,
            rsi=41.8,
            degisim_1ay=-3.32,
            degisim_3ay=12.07,
            platform="",
            aksiyon="BEKLE",
            aksiyon_etiket="Bekle",
            kurulum="",
            guven=0.0,
            gerekce="",
            skor=50.0,
            sinyal="BEKLE",
            sma20=None,
            sma50=None,
            sma200=None,
        )
        endeks_alanlarini_doldur([e], fx_ok=True)
        self.assertEqual(e.platform, "ABD")
        self.assertTrue(e.kurulum)
        self.assertGreater(e.guven, 0)
        self.assertIn(e.aksiyon, ("ARTIR", "KORU", "BEKLE", "AZALT"))
        self.assertNotEqual(e.aksiyon_etiket, "")


class MakroKapisiTest(unittest.TestCase):
    def test_kriz_artir_yasak(self):
        from endeks_yonlendirme import makro_kapisi
        aksiyon, delta, chip, notu = makro_kapisi(
            "ARTIR", "ABD", makro_rejim="KRIZ", ppk_gun=30, fomc_gun=30,
        )
        self.assertEqual(aksiyon, "BEKLE")
        self.assertIn("tavan", chip.lower())

    def test_tl_firsat_abd_artir_koru(self):
        from endeks_yonlendirme import makro_kapisi
        aksiyon, *_ = makro_kapisi(
            "ARTIR", "ABD", makro_rejim="TL_FIRSAT", ppk_gun=30, fomc_gun=30,
        )
        self.assertEqual(aksiyon, "KORU")

    def test_risk_on_abd_artir_kalir(self):
        from endeks_yonlendirme import makro_kapisi
        aksiyon, delta, chip, _ = makro_kapisi(
            "ARTIR", "ABD", makro_rejim="RISK_ON", ppk_gun=30, fomc_gun=30,
        )
        self.assertEqual(aksiyon, "ARTIR")
        self.assertGreater(delta, 0)

    def test_fomc_pencere_artir_koru(self):
        from endeks_yonlendirme import makro_kapisi
        aksiyon, *_ = makro_kapisi(
            "ARTIR", "ABD", makro_rejim="NOTR", ppk_gun=30, fomc_gun=2,
        )
        self.assertEqual(aksiyon, "KORU")

    def test_karar_includes_makro_chip(self):
        k = karar(
            sembol="^NDX",
            fiyat=25000.0,
            rsi=42.0,
            sma20=25200.0,
            sma50=24800.0,
            sma200=22000.0,
            degisim_1ay=-2.0,
            degisim_3ay=10.0,
            fx_ok=True,
            makro_rejim="KRIZ",
            ppk_gun=30,
            fomc_gun=30,
        )
        self.assertEqual(k.teknik_aksiyon, "ARTIR")
        self.assertEqual(k.aksiyon, "BEKLE")
        self.assertTrue(k.makro_chip)


class OzetNedenTest(unittest.TestCase):
    def test_artir_koru_plain_language(self):
        from endeks_yonlendirme import ozet_neden

        e = SimpleNamespace(
            teknik_aksiyon="ARTIR",
            aksiyon="KORU",
            kurulum="Trend içi geri çekilme",
            makro_not="TL_FIRSAT: ABD Artır → Koru",
            makro_chip="Makro: Koru tavan",
            degisim_1ay=-3.3,
            degisim_3ay=12.0,
        )
        text = ozet_neden(e)
        self.assertIn("tut", text.lower())
        self.assertNotIn("dip", text.lower())

    def test_spx_positive_1a_not_called_dip(self):
        from endeks_yonlendirme import ozet_neden

        e = SimpleNamespace(
            teknik_aksiyon="ARTIR",
            aksiyon="KORU",
            kurulum="Trend içi geri çekilme",
            makro_not="TL_FIRSAT: ABD Artır → Koru",
            makro_chip="Makro: Koru tavan",
            platform="ABD",
            sembol="^GSPC",
            degisim_1ay=-0.7,
            degisim_3ay=5.9,
        )
        # Tablo EUR: 1A pozitif — Neden tabloyu kullanmalı
        text = ozet_neden(e, gosterim_1ay=0.62, gosterim_3ay=9.33, gosterim_pb="EUR")
        self.assertIn("1A pozitif", text)
        self.assertIn("+9.3%", text)
        self.assertIn("EUR", text)
        self.assertNotIn("-0.7", text)

    def test_bist_tl_firsat_not_abd_message(self):
        from endeks_yonlendirme import ozet_neden

        e = SimpleNamespace(
            teknik_aksiyon="ARTIR",
            aksiyon="KORU",
            kurulum="Trend içi geri çekilme",
            makro_not="TL_FIRSAT: BIST destek",
            makro_chip="Makro: TL_FIRSAT",
            platform="TR",
            sembol="XU100.IS",
            degisim_1ay=-2.0,
            degisim_3ay=-0.3,
        )
        text = ozet_neden(e, gosterim_1ay=-2.35, gosterim_3ay=-0.32, gosterim_pb="EUR")
        self.assertNotIn("ABD'de agresif", text)
        self.assertIn("-0.3%", text)


if __name__ == "__main__":
    unittest.main()
