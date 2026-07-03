# -*- coding: utf-8 -*-
"""Faz 5 — backtest dürüstlük ve karşı-olgusal simülasyon."""
import unittest

import config
from backtest import BacktestSatir, backtest_karsi_olgusal_metrikleri, backtest_metrikleri


def _satirlar(n=6):
    out = []
    for i in range(n):
        out.append(
            BacktestSatir(
                tarih=f"2025-{i+1:02d}",
                rejim="NOTR" if i < 4 else "RISK_ON",
                rejim_etiket="Nötr",
                eur_try=35.0 + i * 0.5,
                bist100=9000 + i * 100,
                btc_usd=60000 + i * 1000,
                altin_usd=2300 + i * 10,
                vix=18.0,
                cds=260,
                enflasyon=35,
                tcmb=37,
                oncelikli_varlik="EUR",
                agirliklar={"eur_cash": 0.4, "tl_deposit": 0.2, "gold": 0.2, "usd_cash": 0.2},
            )
        )
    return out


class Faz5BacktestTest(unittest.TestCase):
    def test_drift_esigi_config(self):
        sat = _satirlar()
        met = backtest_metrikleri(sat, "TL_FIRSAT")
        self.assertTrue(met.model_drift)
        self.assertLess(met.mevcut_rejim_oran_pct, config.BACKTEST_REJIM_MIN_ORAN)

    def test_karsi_olgusal_uretilir(self):
        sat = _satirlar()
        w = {"eur_cash": 0.5, "gold": 0.3, "tl_deposit": 0.2}
        k = backtest_karsi_olgusal_metrikleri(sat, w, etiket="Test")
        self.assertIsNotNone(k)
        self.assertEqual(k.en_sik_rejim, "SABIT")
        self.assertIsNotNone(k.toplam_getiri_pct)


if __name__ == "__main__":
    unittest.main()
