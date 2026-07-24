# -*- coding: utf-8 -*-
"""Teknik özet — RSI/SMA kural tabanlı okuma."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from signal_engine.explain.tech_snapshot import (
    build_tech_snapshot,
    table_rows_from_snapshot,
    tech_snapshot_from_hisse,
)


class TechSnapshotTest(unittest.TestCase):
    def test_rsi_bands(self):
        self.assertIn("Aşırı satım", build_tech_snapshot(rsi=28).rsi_okuma)
        self.assertIn("Nötr orta", build_tech_snapshot(rsi=53).rsi_okuma)
        self.assertIn("Aşırı alım", build_tech_snapshot(rsi=75).rsi_okuma)

    def test_sma_destek_baski(self):
        s = build_tech_snapshot(fiyat=320.0, sma50=315.0, sma200=300.0, sma20=330.0)
        self.assertIn("Baskı", s.sma20_okuma)
        self.assertIn("Destek", s.sma50_okuma)
        self.assertIn("Destek", s.sma200_okuma)
        self.assertIn("baskı", s.kisa_okuma.lower())
        self.assertIn("Nötr-yukarı", s.uzun_okuma)
        self.assertIn("Kısa vadede baskı", s.ozet)

    def test_both_sma_below(self):
        s = build_tech_snapshot(fiyat=280.0, sma50=315.0, sma200=300.0, sma20=290.0)
        self.assertIn("Zayıf", s.uzun_okuma)

    def test_missing_sma(self):
        s = build_tech_snapshot(fiyat=100.0, rsi=50.0)
        self.assertEqual(s.sma50_okuma, "veri yok")
        self.assertIn("yeterli veri yok", s.uzun_okuma.lower())
        vals = {r[0]: r[1] for r in s.rows}
        self.assertEqual(vals["SMA50"], "—")

    def test_from_hisse(self):
        h = SimpleNamespace(
            fiyat=326.0,
            rsi=53.13,
            sma20=331.71,
            sma50=315.34,
            sma200=300.54,
            signal_v2_regime="RANGE",
            signal_v2_regime_detail="ADX düşük",
            signal_v2_decision="İZLE",
            signal_v2_score=58.0,
            signal_v2_al_price=314.5,
            signal_v2_al_method="spot civarı",
            signal_v2_spot_near=True,
            signal_v2_ichimoku={"buy_zone": False, "note": "bulut üstü ama TK zayıf"},
            signal_v2_ready_note=True,
            signal_v2_small_size=False,
        )
        s = tech_snapshot_from_hisse(h)
        self.assertIn("Nötr orta", s.rsi_okuma)
        self.assertIn("RANGE", s.rejim)
        self.assertFalse(s.ichimoku_buy_zone)
        self.assertIn("bekle", s.aksiyon_okuma.lower())
        self.assertAlmostEqual(s.al_seviyesi, 314.5)
        block = s.prompt_block()
        self.assertIn("RSI(14)", block)
        self.assertIn("Ichimoku", block)
        self.assertIn("Alım seviyesi", block)
        rows = table_rows_from_snapshot(s)
        labels = [r[0] for r in rows]
        self.assertIn("Ichimoku", labels)
        self.assertIn("Alım seviyesi", labels)

    def test_aksiyon_ichimoku_acik_al(self):
        s = build_tech_snapshot(
            fiyat=320.0, rsi=52.0, sma20=318.0, sma50=310.0, sma200=300.0,
            karar="AL", al_seviyesi=319.0, spot_near=True,
            ichimoku_buy_zone=True, ichimoku_note="bulut desteği",
        )
        self.assertIn("açık", s.aksiyon_okuma.lower())
        self.assertIn("kademeli", s.aksiyon_okuma.lower())


if __name__ == "__main__":
    unittest.main()
