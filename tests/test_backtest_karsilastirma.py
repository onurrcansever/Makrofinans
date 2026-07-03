# -*- coding: utf-8 -*-
"""Backtest üç yollu karşılaştırma ve statik referans."""
import unittest

import config
from backtest import (
    BacktestSatir,
    backtest_karsilastirma_uret,
    backtest_karsi_olgusal_metrikleri,
    rejim_dagilimi,
    statik_referans_agirliklari,
)
from investor_profile import YatirimProfili


def _satirlar(n=6, rejim="NOTR"):
    out = []
    for i in range(n):
        out.append(
            BacktestSatir(
                tarih=f"2025-{i+1:02d}",
                rejim=rejim if i < 4 else "ENFLASYON_KORUMA",
                rejim_etiket=rejim,
                eur_try=35.0 + i * 0.3,
                bist100=9000 + i * 50,
                btc_usd=60000 + i * 500,
                altin_usd=2300 + i * 5,
                vix=18.0,
                cds=260,
                enflasyon=35,
                tcmb=37,
                oncelikli_varlik="EUR",
                agirliklar={"eur_cash": 0.4, "tl_deposit": 0.1, "gold": 0.3, "usd_cash": 0.2},
            )
        )
    return out


class BacktestKarsilastirmaTest(unittest.TestCase):
    def test_statik_referans_profil(self):
        d = statik_referans_agirliklari(YatirimProfili(risk="dusuk"))
        self.assertAlmostEqual(sum(d.values()), 1.0, places=4)
        self.assertGreater(d["eur_cash"], d["tl_deposit"])

    def test_rejim_dagilimi(self):
        dag = rejim_dagilimi(_satirlar())
        self.assertAlmostEqual(sum(dag.values()), 100.0, places=0)
        self.assertIn("NOTR", dag)

    def test_karsilastirma_uretilir(self):
        sat = _satirlar()
        w = statik_referans_agirliklari(YatirimProfili(risk="orta"))
        kars = backtest_karsilastirma_uret(
            sat, "NOTR", bugun_agirliklar=w, profil=YatirimProfili(risk="orta")
        )
        self.assertIsNotNone(kars)
        self.assertIsNotNone(kars.referans_statik)
        self.assertIsNotNone(kars.dinamik)
        self.assertIn("Son", kars.ozet)

    def test_sabit_portfoy_etiket(self):
        k = backtest_karsi_olgusal_metrikleri(
            _satirlar(), {"eur_cash": 0.5, "gold": 0.5}, etiket="Test sabit"
        )
        self.assertEqual(k.etiket, "Test sabit")

    def test_dinamik_dezavantaj_esik_config(self):
        self.assertGreaterEqual(config.BACKTEST_UYARI_SHARPE_FARK, 0.1)


if __name__ == "__main__":
    unittest.main()
