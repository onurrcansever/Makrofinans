# -*- coding: utf-8 -*-
"""Sektör F/K değerleme peer — soft bayrak / küçük grup atlama."""
import unittest
from types import SimpleNamespace as SN

from signal_engine.quality.fund_gate import (
    apply_fund_gate_to_code,
    evaluate_fund_gate,
    format_sirket_ozeti_markdown,
)
from signal_engine.quality.peer_valuation import (
    build_peer_valuation_map,
    pe_from_temel,
)


def _h(sembol, pe=None, *, piyasa="NASDAQ", sektor="teknoloji", tur="hisse"):
    return SN(
        sembol=sembol,
        piyasa=piyasa,
        sektor=sektor,
        varlik_turu=tur,
    )


def _cache_pe(pairs):
    """[(sym, pe), ...] → cache dict."""
    return {s: {"trailingPE": pe, "guncelleme": "2026-01-01"} for s, pe in pairs}


class PeerValuationMapTest(unittest.TestCase):
    def test_pe_from_temel_forward_fallback(self):
        self.assertIsNone(pe_from_temel({"trailingPE": -5}))
        self.assertAlmostEqual(
            pe_from_temel({"trailingPE": -1, "forwardPE": 12.0}), 12.0,
        )

    def test_kucuk_grup_bos(self):
        hisseler = [_h(f"A{i}") for i in range(3)]
        cache = _cache_pe([(f"A{i}", 10 + i) for i in range(3)])
        m = build_peer_valuation_map(hisseler, cache)
        self.assertEqual(m, {})

    def test_pahali_ve_ucuz(self):
        # 4 peer: 10, 12, 14, 30 → 30 pahalı (≥1.6× medyan≈13)
        pairs = [("A", 10.0), ("B", 12.0), ("C", 14.0), ("D", 30.0)]
        hisseler = [_h(s) for s, _ in pairs]
        m = build_peer_valuation_map(hisseler, _cache_pe(pairs))
        self.assertIn("D", m)
        self.assertTrue(m["D"].expensive)
        self.assertFalse(m["A"].expensive)
        self.assertGreaterEqual(m["D"].pe_pct, 85.0)
        self.assertGreaterEqual(m["D"].pe_vs_median, 1.6)

    def test_etf_haric(self):
        pairs = [("A", 10), ("B", 12), ("C", 14), ("D", 16), ("ETF1", 5)]
        hisseler = [_h(s) for s, _ in pairs[:4]]
        hisseler.append(_h("ETF1", piyasa="ETF", tur="etf"))
        m = build_peer_valuation_map(hisseler, _cache_pe(pairs))
        self.assertNotIn("ETF1", m)
        self.assertEqual(len(m), 4)

    def test_farkli_sektor_ayri(self):
        tech = [("T1", 10), ("T2", 12), ("T3", 14), ("T4", 40)]
        bank = [("B1", 8), ("B2", 9), ("B3", 10)]  # <4 → yok
        hisseler = [_h(s, sektor="teknoloji") for s, _ in tech]
        hisseler += [_h(s, sektor="banka") for s, _ in bank]
        m = build_peer_valuation_map(hisseler, _cache_pe(tech + bank))
        self.assertIn("T4", m)
        self.assertTrue(m["T4"].expensive)
        self.assertNotIn("B1", m)


class PeerFundGateTest(unittest.TestCase):
    def test_peer_soft_tek_kesmez(self):
        t = {"fcf_y": 1e9, "net_income_y": 1e8, "guncelleme": "2026-01-01"}
        peer = {
            "pe": 40, "pe_median": 20, "pe_pct": 100,
            "peer_n": 5, "expensive": True, "pe_vs_median": 2.0, "note": "x",
        }
        r = evaluate_fund_gate(t, _h("X"), peer=peer)
        self.assertTrue(any("F/K pahalı" in x for x in r.soft_flags))
        self.assertFalse(r.block)
        self.assertEqual(
            apply_fund_gate_to_code("BUY", t, _h("X"), [], peer=peer), "BUY",
        )

    def test_peer_plus_soft_bloklar(self):
        t = {
            "profit_margin_y": -0.02,
            "fcf_y": 1e9,
            "net_income_y": 1e8,
            "guncelleme": "2026-01-01",
        }
        peer = {
            "pe": 40, "pe_median": 20, "pe_pct": 90,
            "peer_n": 4, "expensive": True, "pe_vs_median": 2.0, "note": "x",
        }
        r = evaluate_fund_gate(t, _h("X"), peer=peer)
        self.assertTrue(r.block)
        gates = []
        self.assertEqual(
            apply_fund_gate_to_code("BUY", t, _h("X"), gates, peer=peer),
            "WATCH",
        )
        self.assertTrue(any("Temel kapı" in g for g in gates))

    def test_etf_peer_bypass(self):
        peer = {
            "expensive": True, "pe_pct": 99, "pe_vs_median": 3,
            "peer_n": 4, "pe": 50, "pe_median": 10, "note": "x",
        }
        r = evaluate_fund_gate(
            {"trailingPE": 50, "guncelleme": "2026-01-01"},
            _h("E", piyasa="ETF", tur="etf"),
            peer=peer,
        )
        self.assertFalse(r.applied)

    def test_markdown_peer_satiri(self):
        t = {"revenue_y": 1e9, "trailingPE": 30.0, "guncelleme": "2026-01-01"}
        peer = {
            "pe": 30, "pe_median": 15, "pe_pct": 100,
            "peer_n": 4, "expensive": True, "pe_vs_median": 2.0, "note": "x",
        }
        md = format_sirket_ozeti_markdown(t, peer=peer)
        self.assertIn("Sektör peer F/K", md)
        self.assertIn("pahalı", md)


if __name__ == "__main__":
    unittest.main()
