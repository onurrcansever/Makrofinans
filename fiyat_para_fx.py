# -*- coding: utf-8 -*-
"""FX spot ve tarih hizalama — tek kaynak: Yahoo serileri."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

GBPUSD_BAND = (1.20, 1.45)
EURUSD_BAND = (1.00, 1.25)
USDTRY_JUMP_WARN_PCT = 5.0


class FxUnavailableError(RuntimeError):
    """Yahoo FX serisi yok — sessiz fallback yasak."""


class FxSanityError(ValueError):
    """FX değeri makul bant dışında veya ani sıçrama."""


@dataclass(frozen=True)
class FxSpot:
    eur_try: float
    usd_try: float
    gbp_usd: float
    eur_usd: float
    asof: str
    source: str


def fx_value_at(seri: pd.Series, when: pd.Timestamp) -> Optional[float]:
    """Seride `when` günü veya önceki işlem günü değeri."""
    s = seri.dropna()
    if s.empty:
        return None
    when = pd.Timestamp(when)
    if when in s.index:
        v = float(s.loc[when])
        return v if v > 0 else None
    pos = s.index.searchsorted(when, side="right") - 1
    if pos < 0:
        return None
    v = float(s.iloc[pos])
    return v if v > 0 else None


def fx_window_dates_calendar(
    bar_dates: pd.DatetimeIndex,
    calendar_days: int = 365,
    *,
    max_target_gap_days: int = 14,
) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
    """d1 − calendar_days takvim, en yakın mevcut bar → (d0, d1).

    Hedefe ±max_target_gap_days dışında bar yoksa None (kısa seri / delik).
    """
    if bar_dates is None or len(bar_dates) < 2:
        return None
    idx = pd.DatetimeIndex(bar_dates).sort_values()
    d1 = pd.Timestamp(idx[-1])
    target = d1 - pd.Timedelta(days=int(calendar_days))
    deltas = (idx - target).asi8
    pos = int(abs(deltas).argmin())
    d0 = pd.Timestamp(idx[pos])
    if d0 >= d1:
        return None
    if abs((d0 - target).days) > int(max_target_gap_days):
        return None
    if (d1 - d0).days < int(calendar_days) - 30:
        return None
    return d0, d1


def fx_window_dates(
    bar_dates: pd.DatetimeIndex,
    gun: int,
) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Getiri penceresi uç tarihleri.

    gun >= 252 (1Y): d1 − 365 takvim günü, en yakın mevcut bar.
    Daha kısa pencereler: bar ofseti (gun trading bar).
    """
    if gun >= 252:
        return fx_window_dates_calendar(bar_dates, calendar_days=365)
    if bar_dates is None or len(bar_dates) < gun + 1:
        return None
    idx = pd.DatetimeIndex(bar_dates)
    return pd.Timestamp(idx[-gun - 1]), pd.Timestamp(idx[-1])


def eur_usd_at(
    eur_s: Optional[pd.Series],
    usd_s: Optional[pd.Series],
    eurusd_s: Optional[pd.Series],
    when: pd.Timestamp,
) -> Optional[float]:
    """EURUSD — önce EURUSD=X, yoksa EURTRY/USDTRY."""
    if eurusd_s is not None and not eurusd_s.empty:
        v = fx_value_at(eurusd_s, when)
        if v is not None:
            return v
    eur = fx_value_at(eur_s, when) if eur_s is not None and not eur_s.empty else None
    usd = fx_value_at(usd_s, when) if usd_s is not None and not usd_s.empty else None
    if eur is not None and usd is not None and usd > 0:
        return eur / usd
    return None


def fx_spot_from_series(
    eur_s: Optional[pd.Series],
    usd_s: Optional[pd.Series],
    gbp_s: Optional[pd.Series],
    eurusd_s: Optional[pd.Series] = None,
    asof: Optional[pd.Timestamp] = None,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Yahoo FX serilerinden asof günü spot."""
    if usd_s is None or usd_s.empty:
        return None, None, None, None
    when = pd.Timestamp(asof) if asof is not None else pd.Timestamp(usd_s.index[-1])
    usd = fx_value_at(usd_s, when)
    eur = fx_value_at(eur_s, when) if eur_s is not None and not eur_s.empty else None
    gbp = fx_value_at(gbp_s, when) if gbp_s is not None and not gbp_s.empty else None
    eur_usd = eur_usd_at(eur_s, usd_s, eurusd_s, when)
    return eur, usd, gbp, eur_usd


def assert_fx_plausibility(
    fx: FxSpot,
    usd_s: Optional[pd.Series],
    *,
    label: str = "FX",
) -> None:
    """Dış çapa: GBPUSD/EURUSD bantları; USDTRY 30g >%5 sıçrama.

    Kaba hata backstop'u; asıl koruma Yahoo zorunluluğu + çapraz tutarlılık.
    Örn. GBPUSD=1.27 bant [1.20,1.45] içinde kalır — bu guard tek başına
    eski 1.27 fallback'ini yakalamazdı.
    """
    lo, hi = GBPUSD_BAND
    if not lo <= fx.gbp_usd <= hi:
        raise FxSanityError(f"{label}: GBPUSD={fx.gbp_usd:.4f} bant [{lo},{hi}] dışı")
    lo, hi = EURUSD_BAND
    if not lo <= fx.eur_usd <= hi:
        raise FxSanityError(f"{label}: EURUSD={fx.eur_usd:.4f} bant [{lo},{hi}] dışı")
    if usd_s is not None and not usd_s.empty:
        s = usd_s.dropna()
        if len(s) >= 2:
            tail = s.iloc[-30:] if len(s) >= 30 else s
            jump = abs(float(tail.iloc[-1]) / float(tail.iloc[0]) - 1.0) * 100.0
            if jump > USDTRY_JUMP_WARN_PCT:
                raise FxSanityError(
                    f"{label}: USDTRY son {len(tail)}g sıçrama %{jump:.1f} (>{USDTRY_JUMP_WARN_PCT})"
                )


def kur_tablo_spot(
    snap,
    eur_s: Optional[pd.Series],
    usd_s: Optional[pd.Series],
    gbp_s: Optional[pd.Series],
    eurusd_s: Optional[pd.Series] = None,
    asof: Optional[pd.Timestamp] = None,
    *,
    check_plausibility: bool = True,
) -> FxSpot:
    """
    Tablo fiyat/getiri için spot — yalnızca Yahoo serisi.
    Seri yoksa FxUnavailableError; makul bant dışı FxSanityError.
    """
    if usd_s is None or usd_s.empty:
        raise FxUnavailableError("USDTRY=X serisi yok")
    if eur_s is None or eur_s.empty:
        raise FxUnavailableError("EURTRY=X serisi yok")
    if gbp_s is None or gbp_s.empty:
        raise FxUnavailableError("GBPUSD=X serisi yok")

    when = pd.Timestamp(asof) if asof is not None else pd.Timestamp(usd_s.index[-1])
    eur_y, usd_y, gbp_y, eur_usd_y = fx_spot_from_series(eur_s, usd_s, gbp_s, eurusd_s, asof=when)

    missing = []
    if usd_y is None:
        missing.append("USDTRY")
    if eur_y is None:
        missing.append("EURTRY")
    if gbp_y is None:
        missing.append("GBPUSD")
    if eur_usd_y is None:
        missing.append("EURUSD")
    if missing:
        raise FxUnavailableError(f"FX spot eksik @ {when.date()}: {', '.join(missing)}")

    fx = FxSpot(
        eur_try=float(eur_y),
        usd_try=float(usd_y),
        gbp_usd=float(gbp_y),
        eur_usd=float(eur_usd_y),
        asof=str(when.date()),
        source="Yahoo EURTRY=X / USDTRY=X / GBPUSD=X / EURUSD=X",
    )
    if check_plausibility:
        assert_fx_plausibility(fx, usd_s)
    return fx


def assert_fx_snap_vs_series(
    snap,
    eur_s: Optional[pd.Series],
    usd_s: Optional[pd.Series],
    gbp_s: Optional[pd.Series],
    eurusd_s: Optional[pd.Series] = None,
    *,
    tol_pct: float = 5.0,
    label: str = "SNAP vs Yahoo",
) -> None:
    """MacroSnapshot ile Yahoo uyumsuzsa hata; Yahoo yoksa FxUnavailableError."""
    from fiyat_para import FxCrossSanityError, kur_al

    if usd_s is None or usd_s.empty:
        raise FxUnavailableError(f"{label}: USDTRY serisi yok — SNAP ile karşılaştırılamaz")

    e_snap, u_snap = kur_al(snap)
    e_y, u_y, g_y, _ = fx_spot_from_series(eur_s, usd_s, gbp_s, eurusd_s)
    if u_y is None:
        raise FxUnavailableError(f"{label}: Yahoo USDTRY spot yok")

    err = abs(u_snap / u_y - 1.0) * 100.0
    if err > tol_pct:
        raise FxCrossSanityError(
            f"{label}: USDTRY SNAP={u_snap:.2f} Yahoo={u_y:.2f} sapma %{err:.1f}"
        )
    if e_y and abs(e_snap / e_y - 1.0) * 100.0 > tol_pct:
        raise FxCrossSanityError(
            f"{label}: EURTRY SNAP={e_snap:.2f} Yahoo={e_y:.2f}"
        )
    if g_y and u_y:
        try_y = u_y * g_y
        try_snap = u_snap * g_y
        err_g = abs(try_snap / try_y - 1.0) * 100.0
        if err_g > tol_pct:
            raise FxCrossSanityError(
                f"{label}: TRY/GBP SNAP×GBPUSD={try_snap:.2f} Yahoo={try_y:.2f}"
            )


def assert_price_cross_consistency(
    *,
    gbp: Optional[float] = None,
    usd: Optional[float] = None,
    tl: Optional[float],
    fx: FxSpot,
    tol_pct: float = 0.1,
    label: str = "",
) -> None:
    """TL/USD=USDTRY, USD/GBP=GBPUSD, TL/GBP=USDTRY×GBPUSD — hepsi %0.1 içinde."""
    from fiyat_para import FxCrossSanityError

    if tl is None or tl <= 0:
        raise FxCrossSanityError(f"{label}: TL fiyat geçersiz")

    def _chk(observed: float, implied: float, what: str) -> None:
        err = abs(observed / implied - 1.0) * 100.0
        if err > tol_pct:
            raise FxCrossSanityError(
                f"{label}: {what} sapma %{err:.2f} gözlem={observed:.4f} beklenen={implied:.4f}"
            )

    if usd is not None and usd > 0:
        _chk(tl / usd, fx.usd_try, "TL/USD vs USDTRY")
    if gbp is not None and gbp > 0:
        _chk(tl / gbp, fx.usd_try * fx.gbp_usd, "TL/GBP vs USDTRY×GBPUSD")
        if usd is not None and usd > 0:
            _chk(usd / gbp, fx.gbp_usd, "USD/GBP vs GBPUSD")
