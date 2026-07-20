# -*- coding: utf-8 -*-
"""Eşiğe yakın takip listesi — AL değil; risk kapıları korunur."""
import unittest
from types import SimpleNamespace as SN

from karar_lejant import (
    hisse_lejant_caption,
    hisse_playbook_caption,
)
from stock_scanner import ESIGE_YAKIN_SKOR, esige_yakin_sec


def _h(
    sembol="AAA",
    *,
    code="WATCH",
    skor=64.0,
    regime="RANGE",
    piyasa="NASDAQ",
    quarantine=False,
):
    return SN(
        sembol=sembol,
        signal_v2_code=code,
        signal_v2_score=skor,
        signal_v2_regime=regime,
        skor=skor,
        piyasa=piyasa,
        veri_quarantine=quarantine,
        ad=sembol,
    )


class EsigeYakinTest(unittest.TestCase):
    def test_watch_yakin_gecer(self):
        h = _h(skor=64)
        out = esige_yakin_sec([h], "RISK_ON")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].sembol, "AAA")

    def test_buy_elenir(self):
        out = esige_yakin_sec([_h(code="BUY", skor=70)], "RISK_ON")
        self.assertEqual(out, [])

    def test_skor_dusuk_elenir(self):
        out = esige_yakin_sec([_h(skor=50)], "RISK_ON")
        self.assertEqual(out, [])
        self.assertEqual(ESIGE_YAKIN_SKOR, 62.0)

    def test_trending_down_elenir(self):
        out = esige_yakin_sec(
            [_h(skor=65, regime="TRENDING_DOWN")], "RISK_ON",
        )
        self.assertEqual(out, [])

    def test_kriz_bos(self):
        out = esige_yakin_sec([_h(skor=65)], "KRIZ")
        self.assertEqual(out, [])
        out2 = esige_yakin_sec([_h(skor=65)], "EM_STRES")
        self.assertEqual(out2, [])

    def test_etf_once(self):
        hisse = _h("HISSE", skor=65, piyasa="NASDAQ")
        etf = _h("ETF1", skor=64, piyasa="ETF")
        out = esige_yakin_sec([hisse, etf], "NOTR")
        self.assertEqual([x.sembol for x in out], ["ETF1", "HISSE"])

    def test_quarantine_elenir(self):
        out = esige_yakin_sec([_h(skor=65, quarantine=True)], "NOTR")
        self.assertEqual(out, [])

    def test_lejant_aksiyon_once(self):
        c = hisse_lejant_caption()
        self.assertIn("Şimdi ne yap?", c)
        self.assertIn("Momentum", c)
        self.assertIn("değildir", c)
        p = hisse_playbook_caption()
        self.assertIn("yeni alım yok", p)
        self.assertIn("şimdi alma", p)


if __name__ == "__main__":
    unittest.main()
