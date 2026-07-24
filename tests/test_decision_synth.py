# -*- coding: utf-8 -*-
"""Birleşik karar sentezi birim testleri."""
from __future__ import annotations

from signal_engine.decisions.decision_synth import synthesize_action


def test_reduce_never_upgrades_to_buy():
    r = synthesize_action(
        "REDUCE",
        fund_label="GÜÇLÜ",
        spot_near=True,
        ichimoku_buy_zone=True,
        regime="TRENDING_UP",
        tech_score=90,
    )
    assert r.code == "REDUCE"


def test_watch_does_not_lift_on_saglam_spot_only():
    """Eski bug: SAĞLAM + spot → herkes AL · küçük. Artık İZLE kalmalı."""
    r = synthesize_action(
        "WATCH",
        fund_label="SAĞLAM",
        spot_near=True,
        ichimoku_buy_zone=False,
        regime="TRENDING_UP",
        tech_score=55,
        peer={"expensive": False},
    )
    assert r.code == "WATCH"
    assert r.small_size is False
    assert r.ready_note is True


def test_watch_does_not_lift_low_score_even_with_zones():
    r = synthesize_action(
        "WATCH",
        fund_label="SAĞLAM",
        spot_near=True,
        ichimoku_buy_zone=True,
        regime="TRENDING_UP",
        tech_score=52,  # MSFT tipi — AL eşiğinden uzak
        peer={"expensive": False},
    )
    assert r.code == "WATCH"
    assert r.small_size is False


def test_watch_lifts_only_when_all_strict():
    r = synthesize_action(
        "WATCH",
        fund_label="SAĞLAM",
        spot_near=True,
        ichimoku_buy_zone=True,
        regime="TRENDING_UP",
        tech_score=63,
        peer={"expensive": False},
    )
    assert r.code == "BUY"
    assert r.small_size is True


def test_watch_no_lift_if_expensive():
    r = synthesize_action(
        "WATCH",
        fund_label="SAĞLAM",
        spot_near=True,
        ichimoku_buy_zone=True,
        tech_score=65,
        peer={"expensive": True},
        regime="TRENDING_UP",
    )
    assert r.code == "WATCH"
    assert any("pahalı" in g.lower() for g in r.gates)


def test_watch_no_lift_trending_down():
    r = synthesize_action(
        "WATCH",
        fund_label="SAĞLAM",
        spot_near=True,
        ichimoku_buy_zone=True,
        tech_score=70,
        regime="TRENDING_DOWN",
    )
    assert r.code == "WATCH"


def test_wait_never_lifts():
    r = synthesize_action(
        "WAIT",
        fund_label="GÜÇLÜ",
        spot_near=True,
        ichimoku_buy_zone=True,
        regime="TRENDING_UP",
        tech_score=70,
    )
    assert r.code == "WAIT"


def test_buy_demoted_on_weak_fund():
    r = synthesize_action(
        "BUY",
        fund_label="RİSKLİ",
        spot_near=True,
        tech_score=70,
    )
    assert r.code == "WATCH"


def test_buy_demoted_on_yetersiz_fund():
    r = synthesize_action(
        "BUY",
        fund_label="YETERSİZ",
        spot_near=True,
        tech_score=75,
        ichimoku_buy_zone=True,
    )
    assert r.code == "WATCH"
    r2 = synthesize_action(
        "BUY",
        fund_label="ZAYIF",
        spot_near=True,
        tech_score=75,
    )
    assert r2.code == "WATCH"


def test_etf_dash_fund_label_not_demoted_for_fund():
    """ETF/emtia '—' bilanço yok — temel düşürme uygulanmaz (giriş uzak ayrı)."""
    r = synthesize_action(
        "BUY",
        fund_label="—",
        spot_near=True,
        spot_distance_pct=2.0,
        tech_score=70,
        peer={"expensive": False},
    )
    assert r.code == "BUY"


def test_buy_demoted_expensive_and_neutral_fund():
    r = synthesize_action(
        "BUY",
        fund_label="NÖTR",
        peer={"expensive": True},
        tech_score=70,
    )
    assert r.code == "WATCH"


def test_strong_buy_needs_solid_fund_and_entry():
    r = synthesize_action(
        "STRONG_BUY",
        fund_label="NÖTR",
        spot_near=True,
        peer={"expensive": False},
        tech_score=80,
    )
    assert r.code == "BUY"

    r2 = synthesize_action(
        "STRONG_BUY",
        fund_label="SAĞLAM",
        spot_near=True,
        peer={"expensive": False},
        spot_distance_pct=1.0,
        tech_score=80,
    )
    assert r2.code == "STRONG_BUY"


def test_buy_far_from_entry_demoted():
    r = synthesize_action(
        "BUY",
        fund_label="SAĞLAM",
        spot_distance_pct=20.0,
        ichimoku_buy_zone=False,
        peer={"expensive": False},
        tech_score=70,
    )
    assert r.code == "WATCH"
    assert any("girişin" in g.lower() or "üstünde" in g.lower() for g in r.gates)


def test_buy_far_from_entry_demoted_even_with_ichimoku():
    """Ichimoku buy_zone kovalama izni vermez."""
    r = synthesize_action(
        "BUY",
        fund_label="SAĞLAM",
        spot_distance_pct=18.0,
        ichimoku_buy_zone=True,
        peer={"expensive": False},
        tech_score=72,
    )
    assert r.code == "WATCH"
    assert any("giriş" in g.lower() or "üstünde" in g.lower() for g in r.gates)
