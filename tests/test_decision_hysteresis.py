# -*- coding: utf-8 -*-
"""Histerezis state machine — dizi testleri."""
from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path

from signal_engine.config.loader import load_signal_config
from signal_engine.decisions import history as dh
from signal_engine.decisions.history import (
    DecisionHistoryError,
    canonical_decision_symbol,
    clear_decision_history,
    get_prev_decision,
    update_decision_history,
)
from signal_engine.decisions.state_machine import (
    LEVEL_LABELS,
    decide_with_hysteresis,
    distance_to_next_downgrade,
    distance_to_next_upgrade,
    hysteresis_panel_note,
)
from signal_engine.pipeline import decision_persist_eligible, signal_engine_v2_uygula
from signal_engine.data.bars import BarSeries
from stock_scanner import HisseAnaliz


def _decide(score: float, prev: str = "") -> str:
    cfg = load_signal_config()
    d = cfg.decisions
    return decide_with_hysteresis(
        score,
        prev,
        strong=float(d["strong_buy"]),
        buy=float(d["buy"]),
        watch=float(d["watch"]),
        wait=float(d["wait"]),
        margin=float(d["hysteresis_margin"]),
    )


class DecisionHistoryStorageTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._state = dh.STATE_PATH
        self._tmp = Path(tempfile.mkdtemp()) / "decision_history.json"
        dh.STATE_PATH = str(self._tmp)
        clear_decision_history()

    def tearDown(self):
        clear_decision_history()
        dh.STATE_PATH = self._state

    def test_canonical_symbol_eqqq_ticker_maps_to_yahoo(self):
        self.assertEqual(canonical_decision_symbol("EQQQ"), "EQQQ.L")
        self.assertEqual(canonical_decision_symbol("EQQQ.L"), "EQQQ.L")

    def test_write_ticker_read_yahoo_same_record(self):
        update_decision_history("EQQQ", "BUY", 68.0, asof="2026-07-15")
        code, cold, _ = get_prev_decision("EQQQ.L", asof="2026-07-15")
        self.assertFalse(cold)
        self.assertEqual(code, "BUY")

    def test_write_yahoo_read_ticker_same_record(self):
        update_decision_history("EQQQ.L", "BUY", 68.0, asof="2026-07-15")
        code, cold, _ = get_prev_decision("EQQQ", asof="2026-07-15")
        self.assertFalse(cold)
        self.assertEqual(code, "BUY")

    def test_stored_key_is_canonical(self):
        update_decision_history("EQQQ", "BUY", 68.0, asof="2026-07-15")
        with open(dh.STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("EQQQ.L", data)
        self.assertNotIn("EQQQ", data)

    def test_write_without_asof_is_noop(self):
        update_decision_history("AMAT", "WATCH", 65.0, asof="")
        code, cold, _ = get_prev_decision("AMAT", asof="2026-07-15")
        self.assertTrue(cold)

    def test_non_canonical_key_not_found(self):
        """Ham 'EQQQ' anahtarı ile yazılmış kayıt kanonik okumayla bulunmaz."""
        with open(dh.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"EQQQ": {"code": "BUY", "karar": "AL", "skor": 68, "tarih": "2026-07-15"}}, f)
        code, cold, reason = get_prev_decision("EQQQ.L", asof="2026-07-15")
        self.assertTrue(cold)
        self.assertEqual(code, "")
        self.assertIn("önceki karar yok", reason)

    def test_ttl_uses_asof_not_now(self):
        update_decision_history("AMAT", "WATCH", 65.0, asof="2026-06-01")
        code, cold, reason = get_prev_decision("AMAT", asof="2026-07-15", ttl_days=30)
        self.assertTrue(cold)
        self.assertIn("44 gün önce", reason)

    def test_missing_file_is_cold_start_not_error(self):
        code, cold, reason = get_prev_decision("AMAT", asof="2026-07-15")
        self.assertTrue(cold)
        self.assertIn("önceki karar yok", reason)

    def test_corrupt_file_raises(self):
        with open(dh.STATE_PATH, "w", encoding="utf-8") as f:
            f.write("{broken")
        with self.assertRaises(DecisionHistoryError):
            get_prev_decision("AMAT", asof="2026-07-15")


class HysteresisSequenceTest(unittest.TestCase):

    def test_eqqq_68_then_64_stays_al(self):
        """Yaşanan vaka: 68 AL, sonra 64 hâlâ AL (>=63)."""
        self.assertEqual(_decide(68), "BUY")
        self.assertEqual(_decide(64, "BUY"), "BUY")
        self.assertEqual(LEVEL_LABELS[_decide(64, "BUY")], "AL")

    def test_68_then_62_drops_to_watch(self):
        self.assertEqual(_decide(68), "BUY")
        self.assertEqual(_decide(62, "BUY"), "WATCH")

    def test_watch_65_stays_watch(self):
        self.assertEqual(_decide(65, "WATCH"), "WATCH")

    def test_watch_65_then_69_upgrades_to_buy(self):
        self.assertEqual(_decide(65, "WATCH"), "WATCH")
        self.assertEqual(_decide(69, "WATCH"), "BUY")

    def test_cold_start_64_is_watch(self):
        self.assertEqual(_decide(64), "WATCH")

    def test_reduce_40_then_80_becomes_buy_not_strong(self):
        self.assertEqual(_decide(40), "REDUCE")
        self.assertEqual(_decide(80, "REDUCE"), "BUY")

    def test_reduce_40_then_82_strong_buy(self):
        self.assertEqual(_decide(40), "REDUCE")
        self.assertEqual(_decide(82, "REDUCE"), "STRONG_BUY")

    def test_amat_effective_distance_to_al(self):
        """İZLE'de 65 — AL için 69 gerekir → -4 puan."""
        cfg = load_signal_config()
        up = distance_to_next_upgrade(65, "WATCH", cfg)
        self.assertIsNotNone(up)
        label, dist = up
        self.assertEqual(label, "AL")
        self.assertAlmostEqual(dist, -4.0)

    def test_amat_effective_distance_down_to_bekle(self):
        """İZLE'de 65 — BEKLE'ye düşmek için <49 → +16 puan."""
        cfg = load_signal_config()
        down = distance_to_next_downgrade(65, "WATCH", cfg)
        self.assertIsNotNone(down)
        label, dist = down
        self.assertEqual(label, "BEKLE")
        self.assertAlmostEqual(dist, 16.0)

    def test_hysteresis_panel_note_al_held_at_64(self):
        cfg = load_signal_config()
        note = hysteresis_panel_note(
            64, "BUY", "BUY", cold_start=False, cold_reason="", cfg=cfg,
        )
        self.assertIn("AL'da tutuluyor", note)
        self.assertIn("< 63", note)

    def test_hysteresis_panel_note_cold_start(self):
        cfg = load_signal_config()
        note = hysteresis_panel_note(
            64, "WATCH", "", cold_start=True,
            cold_reason="cold start: önceki karar yok", cfg=cfg,
        )
        self.assertIn("cold start", note)

    def test_buy_hold_floor_63(self):
        """AL'dayken çıkış < 63."""
        self.assertEqual(_decide(63, "BUY"), "BUY")
        self.assertEqual(_decide(62.9, "BUY"), "WATCH")


class DecisionPersistGuardTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._state = dh.STATE_PATH
        self._tmp = Path(tempfile.mkdtemp()) / "decision_history.json"
        dh.STATE_PATH = str(self._tmp)
        clear_decision_history()

    def tearDown(self):
        clear_decision_history()
        dh.STATE_PATH = self._state

    def test_decision_persist_eligible_rejects_quarantine(self):
        h = HisseAnaliz(
            "AMAT", "AMAT", "NASDAQ", 100.0, 0, 0, 0, 0, 0, 50, 50, 50,
            "BEKLE", 65, "test", veri_quarantine=True,
        )
        bars = BarSeries.from_series(__import__("pandas").Series([100.0] * 60))
        self.assertFalse(decision_persist_eligible(h, bars))

    def test_quarantine_does_not_overwrite_history(self):
        update_decision_history("AMAT", "WATCH", 65.0, asof="2026-07-15")
        fix = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
        import pickle
        with fix.open("rb") as f:
            df = pickle.load(f)["df"]
        from macro_data import MacroSnapshot
        from decision_engine import PiyasaVerisi
        with (Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json").open() as f:
            snap_vals = json.load(f)["snap"]
        snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=snap_vals["eur_try"], usd_try=snap_vals["usd_try"],
        ))
        h = __import__("stock_scanner")._hisse_analiz(
            df, "AMAT", "AMAT", "NASDAQ", "teknoloji", "NOTR", snap,
        )
        h.veri_quarantine = True
        h.veri_hatasi = "FX yok (test)"
        with unittest.mock.patch(
            "signal_engine.pipeline.update_decision_history",
        ) as mock_write:
            with unittest.mock.patch(
                "signal_engine.data.live_quote.get_live_quote", return_value=None,
            ):
                signal_engine_v2_uygula([h], df, persist_decision_history=True)
            mock_write.assert_not_called()
        code, cold, _ = get_prev_decision("AMAT", asof="2026-07-15")
        self.assertFalse(cold)
        self.assertEqual(code, "WATCH")

    def test_persist_false_never_writes(self):
        with unittest.mock.patch(
            "signal_engine.pipeline.update_decision_history",
        ) as mock_write:
            h = HisseAnaliz(
                "AMAT", "AMAT", "NASDAQ", 100.0, 0, 0, 0, 0, 0, 50, 50, 50,
                "BEKLE", 65, "test",
            )
            idx = __import__("pandas").date_range("2026-01-01", periods=60, freq="B")
            close = __import__("pandas").Series([100.0 + i * 0.1 for i in range(60)], index=idx)
            df = __import__("pandas").DataFrame({("AMAT", "Close"): close, ("^IXIC", "Close"): close})
            signal_engine_v2_uygula([h], df, persist_decision_history=False)
            mock_write.assert_not_called()

    def test_bars_quarantine_blocks_persist(self):
        h = HisseAnaliz(
            "AMAT", "AMAT", "NASDAQ", 100.0, 0, 0, 0, 0, 0, 50, 50, 50,
            "BEKLE", 65, "test",
        )
        bars = BarSeries.from_series(__import__("pandas").Series([100.0] * 60))
        bars.quarantine = True
        self.assertFalse(decision_persist_eligible(h, bars))


class HysteresisGoldenFixtureTest(unittest.TestCase):
    """Golden JSON'daki EQQQ 68→64 dizisi."""

    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path

        meta = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"
        with meta.open(encoding="utf-8") as f:
            cls.hysteresis = json.load(f).get("hysteresis", {})

    def test_eqqq_sequence_in_fixture(self):
        seq = self.hysteresis.get("EQQQ.L")
        self.assertIsNotNone(seq, msg="golden hysteresis.EQQQ.L eksik")
        prev = ""
        for step in seq:
            score = step["score"]
            exp_code = step["code"]
            got = _decide(score, prev or "")
            self.assertEqual(got, exp_code, msg=f"score={score} prev={prev}")
            prev = got


if __name__ == "__main__":
    unittest.main()
