# -*- coding: utf-8 -*-
from ui_regime_badge import REGIME_SPEC, regime_badge_html


def test_all_regime_badges_render():
    for regime in REGIME_SPEC:
        html = regime_badge_html(regime, "ADX 27", duration_days=12, fresh_change=(regime == "HIGH_VOL"))
        assert regime in html or REGIME_SPEC[regime]["short"] in html
        assert "aria-label" in html


def test_fresh_change_dot():
    html = regime_badge_html("TRENDING_UP", fresh_change=True)
    assert "Yeni rejim" in html or "#2563eb" in html
