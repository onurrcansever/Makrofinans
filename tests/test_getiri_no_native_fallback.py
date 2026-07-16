# -*- coding: utf-8 -*-
"""getiri_kur_ayarli — cross-currency'de native sessiz fallback YASAK."""
from __future__ import annotations

import pandas as pd
import pytest

from fiyat_para import getiri_kur_ayarli, getiri_kur_ayarli_ybb
from fiyat_para_fx import FxUnavailableError


def _fx(n=30):
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    eur = pd.Series([50.0 + i * 0.01 for i in range(n)], index=idx)
    usd = pd.Series([45.0 + i * 0.01 for i in range(n)], index=idx)
    gbp = pd.Series([1.34] * n, index=idx)
    return idx, eur, usd, gbp


def test_bar_dates_missing_raises():
    """Fix-A: bar_dates yok → FxUnavailableError (native değil)."""
    _, eur, usd, gbp = _fx()
    with pytest.raises(FxUnavailableError, match="bar_dates"):
        getiri_kur_ayarli(10.0, "USD", "EUR", 21, eur, usd, gbp, bar_dates=None)


def test_fx_endpoints_missing_raises_not_native():
    """Fix-B: bar_dates var ama pencere/FX uçları yok → FxUnavailableError (native değil)."""
    idx, eur, usd, gbp = _fx(n=10)  # gun=252 için yetersiz
    with pytest.raises(FxUnavailableError, match="FX uçları yok"):
        getiri_kur_ayarli(10.0, "USD", "EUR", 252, eur, usd, gbp, bar_dates=idx)


def test_same_currency_returns_native():
    idx, eur, usd, gbp = _fx()
    assert getiri_kur_ayarli(10.0, "EUR", "EUR", 21, eur, usd, gbp, bar_dates=idx) == 10.0


def test_ybb_empty_eur_cross_raises():
    empty = pd.Series(dtype=float)
    usd = pd.Series([45.0], index=pd.date_range("2026-07-15", periods=1))
    with pytest.raises(FxUnavailableError):
        getiri_kur_ayarli_ybb(10.0, "USD", "EUR", empty, usd)


def test_branches_inventory_documented():
    """Erken-return envanteri — yeni native-fallback eklenmesin diye sabitlenir."""
    import inspect
    import fiyat_para as fp

    src = inspect.getsource(fp.getiri_kur_ayarli)
    assert "FX uçları yok" in src
    assert "bar_dates gerekli" in src
    assert "gun<=0 cross-currency native yasak" in src
    # Yalnızca same-pb native; gun<=0 artık raise
    returns = [ln.strip() for ln in src.splitlines() if "return round(float(r_native" in ln]
    assert len(returns) == 1, returns


def test_gun_zero_cross_raises():
    idx, eur, usd, gbp = _fx()
    with pytest.raises(FxUnavailableError, match="gun<=0"):
        getiri_kur_ayarli(10.0, "USD", "EUR", 0, eur, usd, gbp, bar_dates=idx)