# -*- coding: utf-8 -*-
"""FAZ5: publish-lag + live-only dışlama birim testleri."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from signal_engine.quality.fund_score import compute_fund_score, label_from_score
from signal_engine.quality.fund_score_pit import (
    ANNUAL_PUBLISH_LAG_DAYS,
    LIVE_ONLY_FIELDS,
    QUARTER_PUBLISH_LAG_DAYS,
    available_asof,
    filter_temel_for_mode,
    period_visible_at,
)
from signal_engine.quality.fund_score_ui import fund_score_ui_allowed


def test_publish_lag_quarter_45():
    pe = date(2024, 3, 31)
    assert available_asof(pe, annual=False) == pe + timedelta(days=QUARTER_PUBLISH_LAG_DAYS)
    assert available_asof(pe, annual=False) == date(2024, 5, 15)


def test_publish_lag_annual_90():
    pe = date(2024, 12, 31)
    assert available_asof(pe, annual=True) == pe + timedelta(days=ANNUAL_PUBLISH_LAG_DAYS)
    assert available_asof(pe, annual=True) == date(2025, 3, 31)


def test_period_visible_before_lag_false():
    pe = date(2024, 12, 31)
    # +90 → 2025-03-31; 2025-03-30 henüz yok
    assert period_visible_at(date(2025, 3, 30), pe, annual=True) is False
    assert period_visible_at(date(2025, 3, 31), pe, annual=True) is True


def test_filter_removes_live_only():
    temel = {
        "trailingPE": 20.0,
        "forwardPE": 18.0,
        "revenue_y": 1e9,
        "revenue_y_prev": 9e8,
        "net_income_y": 1e8,
        "fcf_y": 5e7,
        "total_assets_y": 2e9,
        "total_liab_y": 8e8,
        "profit_margin_y": 0.1,
        "targetMeanPrice": 100.0,
        "returnOnEquity": 0.2,
    }
    bt = filter_temel_for_mode(temel, "backtest")
    assert "trailingPE" not in bt
    assert "targetMeanPrice" not in bt
    assert "returnOnEquity" not in bt
    assert "revenue_y" in bt
    assert set(bt) & LIVE_ONLY_FIELDS == set()


def test_backtest_score_excludes_pe_driven_valuation():
    """PE peer / peg live-only → valuation çoğu zaman None veya statement-only."""
    temel = {
        "trailingPE": 8.0,  # ucuz — live'da valuation'ı şişirir
        "forwardPE": 7.0,
        "pegRatio": 0.5,
        "marketCap": 1e9,
        "revenue_y": 1e9,
        "revenue_y_prev": 8e8,
        "net_income_y": 1.5e8,
        "fcf_y": 1.2e8,
        "profit_margin_y": 0.15,
        "total_assets_y": 2e9,
        "total_liab_y": 5e8,
        "period_end_y": "2024-12-31",
    }
    peer_live = {"pe_pct": 5.0, "pe_pct_n": 10}  # çok ucuz
    live = compute_fund_score(temel, peer_live, mode="live")
    bt = compute_fund_score(temel, peer_live, mode="backtest")
    assert live.score is not None
    # Backtest peer PE kullanmamalı — pe_pct peer_ctx'te olsa bile mode filter
    # valuation sütunu PE'siz kalabilir; skor yine quality/growth/health ile gelebilir
    assert "trailingPE" not in filter_temel_for_mode(temel, "backtest")
    # Live valuation pe_pct ile dolu; backtest'te pe okunmaz → valuation farklı/None
    if bt.pillars.get("valuation") is not None and live.pillars.get("valuation") is not None:
        # peer pe backtest'te hâlâ peer_ctx'ten gelebilir — build_peer_ctx backtest'te pe eklemez;
        # burada peer_ctx elle verildi. compute backtest'te pe_pct'i okur!
        # Plan: mode=backtest live-only alanları okumaz — peer pe_pct de valuation live-only.
        pass
    # Sert kural: used_fields ham live-only key içermesin
    assert not any(f in LIVE_ONLY_FIELDS for f in bt.used_fields)


def test_backtest_ignores_peer_pe_percentile():
    """mode=backtest: pe_pct peer bağlamı skor valuation'ına girmemeli."""
    temel = {
        "revenue_y": 1e9,
        "revenue_y_prev": 9e8,
        "fcf_y": 1e8,
        "profit_margin_y": 0.12,
        "total_assets_y": 3e9,
        "total_liab_y": 1e9,
    }
    peer = {"pe_pct": 2.0, "pe_pct_n": 20}  # aşırı ucuz — live'da valuation ↑
    # Patch: backtest should not use pe_pct — enforce in compute_fund_score
    live = compute_fund_score(temel, peer, mode="live")
    bt = compute_fund_score(temel, peer, mode="backtest")
    assert live.pillars.get("valuation") is not None
    assert bt.pillars.get("valuation") is None or "pe_peer_pct" in bt.missing
    # Explicit: pe_peer_pct should be missing in backtest if we strip peer
    # After fix, valuation None or without pe
    assert "pe_peer_pct" in bt.missing or bt.pillars.get("valuation") is None


def test_missing_metrics_no_silent_50():
    r = compute_fund_score({}, mode="live")
    assert r.score is None
    assert r.label == "YETERSİZ"


def test_label_bands():
    assert label_from_score(80) == "GÜÇLÜ"
    assert label_from_score(64) == "SAĞLAM"
    assert label_from_score(52) == "NÖTR"
    assert label_from_score(42) == "ZAYIF"
    assert label_from_score(41) == "RİSKLİ"
    assert label_from_score(None) == "YETERSİZ"


def test_ui_gate_blocks_indicative():
    summary = {
        "look_ahead_clean": True,
        "indicative_only": True,
        "sample_adequate": False,
        "n_pit_symbols": 100,
        "n_cross_section": 10,
    }
    # FORCE kapalıyken indicative engeller
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"FUND_SCORE_UI_FORCE": "0", "FUND_SCORE_UI": "0"}, clear=False):
        with patch("signal_engine.quality.fund_score_ui._force_on", return_value=False):
            with patch("signal_engine.quality.fund_score_ui._ui_want", return_value=False):
                ok, reason = fund_score_ui_allowed(summary)
    assert ok is False
    assert "indicative" in reason.lower() or "indicative_only" in reason


def test_ui_force_opens_for_dev():
    summary = {
        "look_ahead_clean": True,
        "indicative_only": True,
        "sample_adequate": False,
        "n_pit_symbols": 0,
        "n_cross_section": 0,
    }
    from unittest.mock import patch

    with patch("signal_engine.quality.fund_score_ui._force_on", return_value=True):
        ok, reason = fund_score_ui_allowed(summary)
    assert ok is True
    assert "FORCE" in reason or "geliştirme" in reason.lower() or "deneysel" in reason.lower()
