# -*- coding: utf-8 -*-
"""Karar seviyesinde golden — skor değil AL/İZLE/AZALT pin."""
from __future__ import annotations

import json
import os
import pickle
import unittest
import unittest.mock
from pathlib import Path

from signal_engine.decisions.history import clear_decision_history
from signal_engine.decisions.state_machine import decide_with_hysteresis, LEVEL_LABELS
from signal_engine.pipeline import signal_engine_v2_uygula
from signal_engine.config.loader import load_signal_config
from stock_scanner import _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"
META = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.json"


class DecisionLevelGoldenTest(unittest.TestCase):
    """Filtre iddiası: aynı fixture → aynı karar kodu (eşik bandı dahil)."""

    @classmethod
    def setUpClass(cls):
        cls._hist = os.environ.get("DECISION_HISTORY_PATH")
        cls._tmp = Path(__file__).resolve().parent / ".tmp_decision_golden_history.json"
        os.environ["DECISION_HISTORY_PATH"] = str(cls._tmp)
        import signal_engine.decisions.history as dh
        dh.STATE_PATH = str(cls._tmp)
        clear_decision_history()

        with FIX.open("rb") as f:
            blob = pickle.load(f)
        with META.open(encoding="utf-8") as f:
            meta = json.load(f)
        cls.df = blob["df"]
        cls.golden = meta["golden"]
        cls.hysteresis = meta.get("hysteresis") or {}
        from macro_data import MacroSnapshot
        from decision_engine import PiyasaVerisi
        from etf_universe import REVOLUT_ETFLER

        snap = blob["snap"]
        cls.snap = MacroSnapshot(veri=PiyasaVerisi(
            eur_try=snap["eur_try"], usd_try=snap["usd_try"],
        ))
        cls.etf = {x[0]: x for x in REVOLUT_ETFLER}

    @classmethod
    def tearDownClass(cls):
        clear_decision_history()
        if cls._tmp.exists():
            cls._tmp.unlink()
        if cls._hist is None:
            os.environ.pop("DECISION_HISTORY_PATH", None)
        else:
            os.environ["DECISION_HISTORY_PATH"] = cls._hist

    def _run(self, sym: str, *, persist: bool = False):
        clear_decision_history()
        if sym in self.etf:
            t = self.etf[sym]
            h = _hisse_analiz(
                self.df, t[0], t[1], "ETF", t[2], "NOTR", self.snap,
                isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
            )
        else:
            h = _hisse_analiz(self.df, sym, sym, "NASDAQ", "teknoloji", "NOTR", self.snap)
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula(
                [h], self.df, profil_risk="orta", persist_decision_history=persist,
            )
        return h

    def test_all_golden_decisions_pinned(self):
        for sym, exp in self.golden.items():
            with self.subTest(sym=sym):
                h = self._run(sym)
                self.assertEqual(h.signal_v2_code, exp["code"], msg=f"{sym} code")
                self.assertEqual(h.signal_v2_decision, exp["decision"], msg=f"{sym} label")

    def test_veur_below_buy_threshold_is_izle_not_al(self):
        """Eşik bandı: VEUR pin <64 → İZLE."""
        h = self._run("VEUR.L")
        self.assertLess(h.signal_v2_score, 64.0)
        self.assertEqual(h.signal_v2_code, "WATCH")
        self.assertEqual(h.signal_v2_decision, "İZLE")

    def test_msft_is_azalt(self):
        h = self._run("MSFT")
        self.assertEqual(h.signal_v2_code, "REDUCE")
        self.assertEqual(h.signal_v2_decision, "AZALT")

    def test_eqqq_hysteresis_sequence_from_golden(self):
        cfg = load_signal_config()
        d = cfg.decisions
        seq = self.hysteresis["EQQQ.L"]
        prev = ""
        for step in seq:
            code = decide_with_hysteresis(
                float(step["score"]),
                step.get("prev") or prev,
                strong=float(d["strong_buy"]),
                buy=float(d["buy"]),
                watch=float(d["watch"]),
                wait=float(d["wait"]),
                margin=float(d["hysteresis_margin"]),
            )
            self.assertEqual(code, step["code"], msg=step)
            self.assertEqual(LEVEL_LABELS[code], step["decision"], msg=step)
            prev = code


if __name__ == "__main__":
    unittest.main()
