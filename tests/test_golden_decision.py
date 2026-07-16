# -*- coding: utf-8 -*-
"""Karar seviyesinde golden pin — skor + nihai karar (cold start)."""
from __future__ import annotations

import os
import pickle
import unittest.mock
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from signal_engine.decisions.history import clear_decision_history
from signal_engine.pipeline import signal_engine_v2_uygula
from stock_scanner import _hisse_analiz

FIX = Path(__file__).resolve().parent / "fixtures" / "signal_golden_20260715.pkl"

GOLDEN = [
    ("AMAT", 65, "İZLE"),
    ("EQQQ.L", 64, "İZLE"),
    ("CSCO", 64, "İZLE"),
    ("MSFT", 40, "AZALT"),
    ("IS3N.DE", 64, "İZLE"),  # round(63.7)
    ("VEUR.L", 63, "İZLE"),  # round(62.6)
]


@dataclass
class DecisionResult:
    skor: float
    nihai_karar: str
    prev_code: Optional[str]


@pytest.fixture(scope="module")
def fixture_15tem():
    with FIX.open("rb") as f:
        blob = pickle.load(f)
    from macro_data import MacroSnapshot
    from decision_engine import PiyasaVerisi
    from etf_universe import REVOLUT_ETFLER

    snap_v = blob["snap"]
    snap = MacroSnapshot(veri=PiyasaVerisi(
        eur_try=snap_v["eur_try"], usd_try=snap_v["usd_try"],
    ))
    return {
        "df": blob["df"],
        "snap": snap,
        "etf": {x[0]: x for x in REVOLUT_ETFLER},
    }


@pytest.fixture
def cold_start_history(tmp_path):
    """Gerçek .decision_history.json'a dokunmaz — izole temp path."""
    prev_env = os.environ.get("DECISION_HISTORY_PATH")
    hist = tmp_path / "decision_history_golden.json"
    os.environ["DECISION_HISTORY_PATH"] = str(hist)
    import signal_engine.decisions.history as dh

    prev_state = dh.STATE_PATH
    dh.STATE_PATH = str(hist)
    clear_decision_history()
    try:
        yield hist
    finally:
        clear_decision_history()
        dh.STATE_PATH = prev_state
        if prev_env is None:
            os.environ.pop("DECISION_HISTORY_PATH", None)
        else:
            os.environ["DECISION_HISTORY_PATH"] = prev_env


def score_and_decide(fixture_15tem, sembol: str, *, prev_code=None) -> DecisionResult:
    clear_decision_history()
    df = fixture_15tem["df"]
    snap = fixture_15tem["snap"]
    etf = fixture_15tem["etf"]
    if sembol in etf:
        t = etf[sembol]
        h = _hisse_analiz(
            df, t[0], t[1], "ETF", t[2], "NOTR", snap,
            isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
        )
    else:
        h = _hisse_analiz(df, sembol, sembol, "NASDAQ", "teknoloji", "NOTR", snap)
    with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
        signal_engine_v2_uygula(
            [h], df, profil_risk="orta", persist_decision_history=False,
        )
    # cold start: prev_code=None — history boş; pipeline get_prev_decision cold döner
    assert prev_code is None
    return DecisionResult(
        skor=float(h.signal_v2_score),
        nihai_karar=h.signal_v2_decision,
        prev_code=h.signal_v2_prev_code or None,
    )


def test_golden_karar(fixture_15tem, cold_start_history):
    for sembol, beklenen_skor, beklenen_karar in GOLDEN:
        result = score_and_decide(fixture_15tem, sembol, prev_code=None)
        ok_skor = round(result.skor) == beklenen_skor
        ok_karar = result.nihai_karar == beklenen_karar
        assert ok_skor and ok_karar, (
            f"{sembol}: skor {result.skor:.1f} (round={round(result.skor)}) "
            f"!= {beklenen_skor} · karar {result.nihai_karar} != {beklenen_karar}"
        )
        assert result.prev_code is None, (
            f"{sembol}: prev_code={result.prev_code!r} (cold start bekleniyordu); "
            f"skor={result.skor:.1f} karar={result.nihai_karar}"
        )
