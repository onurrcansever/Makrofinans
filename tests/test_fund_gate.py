# -*- coding: utf-8 -*-
"""Temel finans kapısı — AL → İZLE kuralları."""
import unittest
from types import SimpleNamespace as SN

from signal_engine.quality.fund_gate import (
    apply_fund_gate_to_code,
    evaluate_fund_gate,
    format_sirket_ozeti_markdown,
)


def _hisse(**kw):
    d = dict(piyasa="NASDAQ", varlik_turu="hisse", sembol="TEST")
    d.update(kw)
    return SN(**d)


class FundGateTest(unittest.TestCase):
    def test_etf_bypass(self):
        r = evaluate_fund_gate(
            {"fcf_y": -1e9, "net_income_y": -1e9, "quoteType": "ETF"},
            _hisse(piyasa="ETF", varlik_turu="etf"),
        )
        self.assertFalse(r.applied)
        self.assertFalse(r.block)

    def test_eksik_veri_noop(self):
        r = evaluate_fund_gate({}, _hisse())
        self.assertFalse(r.block)
        code = apply_fund_gate_to_code("BUY", {}, _hisse(), [])
        self.assertEqual(code, "BUY")

    def test_hard_fcf_ve_zarar(self):
        t = {"fcf_y": -1e8, "net_income_y": -5e7, "guncelleme": "2026-01-01"}
        r = evaluate_fund_gate(t, _hisse())
        self.assertTrue(r.block)
        self.assertTrue(any("FCF" in x for x in r.hard_flags))
        gates = []
        self.assertEqual(apply_fund_gate_to_code("BUY", t, _hisse(), gates), "WATCH")
        self.assertTrue(any("Temel kapı" in g for g in gates))

    def test_hard_analist_strong_sell(self):
        t = {"recommendationKey": "strong_sell", "guncelleme": "2026-01-01"}
        r = evaluate_fund_gate(t, _hisse())
        self.assertTrue(r.block)

    def test_hard_kaldirac_fcf(self):
        t = {
            "total_assets_y": 100.0,
            "total_liab_y": 90.0,
            "fcf_y": -1.0,
            "guncelleme": "2026-01-01",
        }
        r = evaluate_fund_gate(t, _hisse())
        self.assertTrue(r.block)
        self.assertTrue(any("kaldıraç" in x.lower() or "L/A" in x for x in r.hard_flags))

    def test_soft_iki_bloklar(self):
        t = {
            "profit_margin_y": -0.05,
            "revenue_y": 80.0,
            "revenue_y_prev": 100.0,
            "guncelleme": "2026-01-01",
        }
        r = evaluate_fund_gate(t, _hisse())
        self.assertGreaterEqual(len(r.soft_flags), 2)
        self.assertTrue(r.block)

    def test_soft_tek_kesmez(self):
        t = {
            "profit_margin_y": -0.02,
            "fcf_y": 1e9,
            "net_income_y": 1e8,
            "guncelleme": "2026-01-01",
        }
        r = evaluate_fund_gate(t, _hisse())
        self.assertFalse(r.block)
        self.assertEqual(len(r.soft_flags), 1)

    def test_watch_degismez(self):
        t = {"fcf_y": -1, "net_income_y": -1, "guncelleme": "2026-01-01"}
        gates = []
        self.assertEqual(apply_fund_gate_to_code("WATCH", t, _hisse(), gates), "WATCH")
        self.assertEqual(gates, [])

    def test_markdown_karara_etki(self):
        t = {
            "revenue_y": 1e9,
            "net_income_y": -1e8,
            "fcf_y": -1e8,
            "guncelleme": "2026-01-01",
        }
        md = format_sirket_ozeti_markdown(t)
        self.assertIn("Şirket özeti", md)
        self.assertIn("AL → İZLE", md)


if __name__ == "__main__":
    unittest.main()
