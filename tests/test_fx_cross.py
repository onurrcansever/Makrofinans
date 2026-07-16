# -*- coding: utf-8 -*-
"""FX çapraz kuru ve GBP→TL getiri dönüşümü."""
from __future__ import annotations

import pickle

import pandas as pd
import pytest

from fiyat_para import (
    FxCrossSanityError,
    assert_fx_cross_sanity,
    getiri_kur_ayarli,
    tablo_fiyat,
    try_per_eur_from_usd,
    try_per_gbp,
)
from fiyat_para_fx import assert_fx_snap_vs_series


def test_try_per_gbp_is_multiply_not_divide():
    usdtry, gbpusd = 57.0, 1.34
    assert try_per_gbp(usdtry, gbpusd) == pytest.approx(76.38, rel=1e-4)
    assert try_per_gbp(usdtry, gbpusd) != pytest.approx(usdtry / gbpusd)


def test_try_per_eur_from_usd_is_multiply():
    assert try_per_eur_from_usd(57.0, 1.08) == pytest.approx(61.56, rel=1e-4)


def test_fx_cross_sanity_catches_wrong_formula():
    with pytest.raises(FxCrossSanityError):
        assert_fx_cross_sanity(
            usd_try=57.0,
            gbp_usd=1.34,
            gbp_settlement=541.0,
            tl_price=32400.34,
            label="EQQQ",
        )


def test_fx_cross_sanity_user_panel_mismatch():
    """32400 TL / ~541 GBP vs TRY/GBP=63 — %5+ sapma."""
    with pytest.raises(FxCrossSanityError):
        assert_fx_cross_sanity(
            usd_try=47.0258,
            gbp_usd=1.3397,
            gbp_settlement=540.9,
            tl_price=32400.34,
            label="EQQQ panel",
        )


def test_fx_snap_vs_yahoo_catches_57_vs_47():
    from decision_engine import PiyasaVerisi
    from macro_data import MacroSnapshot

    snap = MacroSnapshot(veri=PiyasaVerisi(eur_try=53.04, usd_try=57.0))
    usd_s = pd.Series([47.0], index=pd.date_range("2026-07-15", periods=1))
    eur_s = pd.Series([53.75], index=usd_s.index)
    gbp_s = pd.Series([1.3397], index=usd_s.index)
    with pytest.raises(FxCrossSanityError, match="USDTRY"):
        assert_fx_snap_vs_series(snap, eur_s, usd_s, gbp_s)


def test_getiri_gbp_hisse_tl_not_usd_only_conversion():
    n = 252
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    gbp_usd = pd.Series([1.40 - 0.20 * i / (n - 1) for i in range(n)], index=idx)
    usd_try = pd.Series([40.0 + 17.0 * i / (n - 1) for i in range(n)], index=idx)
    eur_try = usd_try / 1.08
    r_gbp = 10.0
    r = getiri_kur_ayarli(r_gbp, "GBP", "TL", 251, eur_try, usd_try, gbp_usd, bar_dates=idx)
    assert r is not None
    naive_usd = (1 + r_gbp / 100) * (float(usd_try.iloc[-1]) / float(usd_try.iloc[0])) - 1
    assert abs(r / 100 - naive_usd) > 0.05
    assert 25.0 < r < 35.0


def test_tablo_fiyat_gbp_matches_cross():
    from fiyat_para_fx import kur_tablo_spot
    from decision_engine import PiyasaVerisi
    from macro_data import MacroSnapshot
    import pickle
    from signal_engine.data.bars import _extract_close

    df = pickle.load(open("tests/fixtures/signal_golden_20260715.pkl", "rb"))["df"]
    et = _extract_close(df, "EURTRY=X")
    ut = _extract_close(df, "USDTRY=X")
    gbp = _extract_close(df, "GBPUSD=X")
    eurusd = _extract_close(df, "EURUSD=X")
    snap = MacroSnapshot(veri=PiyasaVerisi(eur_try=53.75, usd_try=47.0258))
    fx = kur_tablo_spot(snap, et, ut, gbp, eurusd)
    tl = tablo_fiyat(533.44, "TL", fx.eur_try, fx.usd_try, quote_currency="GBP", gbp_usd=fx.gbp_usd)
    usd = tablo_fiyat(533.44, "USD", fx.eur_try, fx.usd_try, quote_currency="GBP", gbp_usd=fx.gbp_usd)
    assert usd == pytest.approx(533.44 * fx.gbp_usd, rel=1e-3)
    assert tl == pytest.approx(533.44 * fx.usd_try * fx.gbp_usd, rel=1e-3)


def test_getiri_kur_ayarli_date_aligned_matches_compound():
    from fiyat_para_fx import fx_window_dates
    from signal_engine.data.bars import BarSeries, pct_change_calendar, _extract_close

    df = pickle.load(open("tests/fixtures/signal_golden_20260715.pkl", "rb"))["df"]
    bars = BarSeries.from_df(df, "EQQQ.L")
    ut = _extract_close(df, "USDTRY=X")
    gbp = _extract_close(df, "GBPUSD=X")
    et = _extract_close(df, "EURTRY=X")
    d1y = pct_change_calendar(bars.close, 365)
    tl1y = getiri_kur_ayarli(
        d1y, "GBP", "TL", 252, et, ut, gbp, bar_dates=bars.close.index,
    )
    w0, w1 = fx_window_dates(bars.close.index, 252)
    tpg0 = try_per_gbp(
        float(ut.reindex([w0], method="ffill").iloc[0]),
        float(gbp.reindex([w0], method="ffill").iloc[0]),
    )
    tpg1 = try_per_gbp(
        float(ut.reindex([w1], method="ffill").iloc[0]),
        float(gbp.reindex([w1], method="ffill").iloc[0]),
    )
    compound = ((1 + d1y / 100) * (tpg1 / tpg0) - 1) * 100
    assert abs(tl1y - compound) < 0.05
