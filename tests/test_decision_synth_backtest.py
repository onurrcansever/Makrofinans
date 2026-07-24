# -*- coding: utf-8 -*-
"""Sentez A/B backtest — sentetik fiyat ile offline smoke."""
from __future__ import annotations

import numpy as np
import pandas as pd

from signal_engine.backtest.decision_synth_backtest import (
    decide_pair_at,
    generate_synth_ab_report,
    walk_symbol_ab,
    write_synth_ab_report,
)
from signal_engine.backtest.signal_backtest import assert_no_lookahead


def _synthetic_close(n: int = 800, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, n)
    # trend parçaları
    rets[200:350] += 0.0015
    rets[500:650] -= 0.0008
    px = 100 * np.cumprod(1 + rets)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    return pd.Series(px, index=idx)


def test_decide_pair_no_crash():
    c = _synthetic_close()
    b = _synthetic_close(seed=9)
    base, synth, meta = decide_pair_at(c, b, 400)
    assert base in ("REDUCE", "WAIT", "WATCH", "BUY", "STRONG_BUY")
    assert synth in ("REDUCE", "WAIT", "WATCH", "BUY", "STRONG_BUY")
    assert "score" in meta


def test_walk_and_report_offline(tmp_path):
    c = _synthetic_close()
    b = _synthetic_close(seed=3)
    assert assert_no_lookahead(c) is True
    row = walk_symbol_ab(c, b, "SYN", step=10)
    assert row.bars == len(c)
    report = generate_synth_ab_report({"SYN": c}, b, step=10, lookahead_ok=True)
    assert report.symbols
    assert report.confidence_note
    out = write_synth_ab_report(report, path=tmp_path / "decision_synth_ab_report.json")
    assert out.exists()
    md = out.with_name("decision_synth_ab_report.md")
    # write always to REPORT_DIR for md — check json only here
    data = out.read_text(encoding="utf-8")
    assert "aggregate" in data
    assert "fund_mode" in data
