# -*- coding: utf-8 -*-
"""Temel skor etiket doğruluğu — yanlış YETERSİZ olmamalı."""
from __future__ import annotations

from signal_engine.quality.fund_score import (
    compute_fund_score,
    is_etf_or_emtia,
    temel_fund_yeterli,
)


def test_rich_equity_not_yetersiz():
    temel = {
        "trailingPE": 22.0,
        "forwardPE": 18.0,
        "profitMargins": 0.12,
        "profit_margin_y": 0.11,
        "revenue_y": 1e11,
        "revenue_y_prev": 9e10,
        "net_income_y": 1.2e10,
        "fcf_y": 1e10,
        "returnOnEquity": 0.18,
        "total_assets_y": 2e11,
        "total_liab_y": 1e11,
        "debtToEquity": 50.0,
        "currentRatio": 1.2,
        "pegRatio": 1.5,
        "marketCap": 5e11,
        "earningsGrowth": 0.1,
        "revenueGrowth": 0.08,
        "quoteType": "EQUITY",
    }
    assert temel_fund_yeterli(temel) is True
    r = compute_fund_score(temel, {}, mode="live")
    assert r.score is not None
    assert r.label in ("GÜÇLÜ", "SAĞLAM", "NÖTR", "ZAYIF", "RİSKLİ")
    assert r.label != "YETERSİZ"


def test_empty_is_yetersiz():
    assert temel_fund_yeterli({}) is False
    assert compute_fund_score({}, mode="live").label == "YETERSİZ"


def test_etf_not_scored_as_fake_neutral():
    class H:
        piyasa = "ETF"
        varlik_turu = "etf"
        sembol = "EQQQ.L"

    assert is_etf_or_emtia(H()) is True
    assert temel_fund_yeterli({"quoteType": "ETF", "trailingPE": 20}) is False


def test_unh_like_thin_margin_still_labeled():
    """Sigorta tipi düşük marj — yine skor üretilir (YETERSİZ değil)."""
    temel = {
        "trailingPE": 31.0,
        "forwardPE": 19.0,
        "profitMargins": 0.031,
        "profit_margin_y": 0.027,
        "revenue_y": 4.4e11,
        "revenue_y_prev": 4.0e11,
        "net_income_y": 1.2e10,
        "fcf_y": 1.6e10,
        "returnOnEquity": 0.14,
        "total_assets_y": 3.0e11,
        "total_liab_y": 2.0e11,
        "debtToEquity": 69.0,
        "currentRatio": 0.78,
        "pegRatio": 1.4,
        "marketCap": 3.8e11,
        "earningsGrowth": 0.6,
        "revenueGrowth": 0.004,
        "quoteType": "EQUITY",
    }
    r = compute_fund_score(temel, {}, mode="live")
    assert r.score is not None
    assert r.label in ("SAĞLAM", "NÖTR", "ZAYIF", "GÜÇLÜ")
