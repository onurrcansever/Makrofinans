# -*- coding: utf-8 -*-
"""Özet T/A/H chip — gösterim; AL kararını etkilemez."""
import unittest
from types import SimpleNamespace as SN

from hisse_ozet_chip import ozet_chip_html, ozet_chip_metin, ozet_parcalar
from signal_engine.decisions.state_machine import format_score_vs_threshold_line
from signal_engine.config.loader import load_signal_config


def _h(skor=63, regime="RANGE", haber=""):
    return SN(
        skor=skor,
        signal_v2_score=skor,
        signal_v2_regime=regime,
        haber_notu=haber,
        sembol="TEST",
    )


class OzetChipTest(unittest.TestCase):
    def test_teknik_yukselis(self):
        t, a, h = ozet_parcalar(_h(70), buy_threshold=64)
        self.assertEqual(t, "Yükseliş")
        self.assertEqual(a, "—")
        self.assertEqual(h, "—")

    def test_teknik_zayif_trend_down(self):
        t, _, _ = ozet_parcalar(_h(70, regime="TRENDING_DOWN"), buy_threshold=64)
        self.assertEqual(t, "Zayıf")

    def test_analist_buy(self):
        _, a, _ = ozet_parcalar(
            _h(50),
            temel={"recommendationKey": "buy"},
            buy_threshold=64,
        )
        self.assertEqual(a, "Al")

    def test_haber_var(self):
        _, _, h = ozet_parcalar(_h(50, haber="Olumsuz akış"), buy_threshold=64)
        self.assertEqual(h, "Var")

    def test_html_contains_chips(self):
        html = ozet_chip_html(_h(70), buy_threshold=64)
        self.assertIn("T:Yükseliş", html)
        self.assertIn("<span", html)

    def test_metin(self):
        self.assertIn("T:Nötr", ozet_chip_metin(_h(50), buy_threshold=64))


class ScoreThresholdLineTest(unittest.TestCase):
    def test_izle_cumlesi(self):
        cfg = load_signal_config()
        line = format_score_vs_threshold_line(63, "WATCH", "", cfg)
        self.assertIn("Teknik skor 63", line)
        self.assertIn("AL eşiği 64", line)
        self.assertIn("≥66", line)
        self.assertIn("İZLE", line)


if __name__ == "__main__":
    unittest.main()
