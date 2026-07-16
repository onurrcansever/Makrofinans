# -*- coding: utf-8 -*-
"""Tablo fiyatları için para birimi tespiti ve dönüşüm."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

GOSTERIM_PB_LIST = ("EUR", "TL", "USD")


def try_per_gbp(usd_try: float, gbp_usd: float) -> float:
    """TRY/GBP çapraz kuru — Yahoo: USDTRY (TRY/USD) × GBPUSD (USD/GBP)."""
    return float(usd_try) * float(gbp_usd)


def try_per_eur_from_usd(usd_try: float, eur_usd: float) -> float:
    """TRY/EUR — USDTRY × EURUSD (EURTRY serisi yoksa türetme)."""
    return float(usd_try) * float(eur_usd)


class FxCrossSanityError(ValueError):
    """Hesaplanan FX çaprazı ile fiyat oranı uyuşmuyor."""


def _require_gbp_usd(gbp_usd: Optional[float], ctx: str = "") -> float:
    if gbp_usd is None or gbp_usd <= 0:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(f"GBPUSD gerekli{': ' + ctx if ctx else ''}")
    return float(gbp_usd)


def _require_eur_usd(eur_usd: Optional[float], ctx: str = "") -> float:
    if eur_usd is None or eur_usd <= 0:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(f"EURUSD gerekli{': ' + ctx if ctx else ''}")
    return float(eur_usd)


def assert_fx_price_cross(
    *,
    src_pb: str,
    gosterim_pb: str,
    src_amount: float,
    display_amount: float,
    usd_try: float,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    tol_pct: float = 0.1,
    label: str = "",
) -> None:
    """Gösterim fiyatının pinlenen FX ile tutarlı olduğunu doğrular."""
    if src_amount <= 0 or display_amount <= 0:
        raise FxCrossSanityError(f"{label}: geçersiz fiyat")
    src = src_pb.upper()
    dst = gosterim_pb.upper()
    if src == dst:
        return
    if src == "GBP" and dst == "USD":
        implied = src_amount * _require_gbp_usd(gbp_usd, label)
        err = abs(display_amount / implied - 1.0) * 100.0
        if err > tol_pct:
            raise FxCrossSanityError(
                f"{label}: GBP→USD %{err:.2f} (gözlem={display_amount:.2f} beklenen={implied:.2f})"
            )
    elif src == "GBP" and dst == "TL":
        assert_fx_cross_sanity(
            usd_try=usd_try,
            gbp_usd=_require_gbp_usd(gbp_usd, label),
            gbp_settlement=src_amount,
            tl_price=display_amount,
            tol_pct=max(tol_pct, 2.0),
            label=label,
        )
    elif src == "EUR" and dst == "USD":
        implied = src_amount * _require_eur_usd(eur_usd, label)
        err = abs(display_amount / implied - 1.0) * 100.0
        if err > tol_pct:
            raise FxCrossSanityError(
                f"{label}: EUR→USD %{err:.2f} (gözlem={display_amount:.2f} beklenen={implied:.2f})"
            )
    elif src == "GBP" and dst == "EUR":
        implied = src_amount * _require_gbp_usd(gbp_usd, label) / _require_eur_usd(eur_usd, label)
        err = abs(display_amount / implied - 1.0) * 100.0
        if err > tol_pct:
            raise FxCrossSanityError(
                f"{label}: GBP→EUR %{err:.2f} (gözlem={display_amount:.2f} beklenen={implied:.2f})"
            )
    elif src == "USD" and dst == "TL":
        implied = src_amount * usd_try
        err = abs(display_amount / implied - 1.0) * 100.0
        if err > tol_pct:
            raise FxCrossSanityError(f"{label}: USD→TL %{err:.2f}")


def parse_display_amount(text: str) -> Optional[float]:
    """'623.51 EUR' / '33,607 TL' gibi gösterim metninden sayı çıkarır."""
    if not text or text in ("—", "-", "Şimdi", "Parça"):
        return None
    m = re.search(r"([\d.,]+)", str(text).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def fiyat_al_display_cross_warning(
    fiyat_display: Optional[float],
    al_display: str,
    *,
    tol_pct: float = 0.15,
    magnitude_ratio_max: float = 10.0,
) -> Optional[str]:
    """
    FİYAT sütunu ile AL seviyesi aynı PB ve mertebede mi?
    100× sapma (GBp/GBP karışımı) veya %15+ fark varsa uyarı metni döner.
    """
    al_amt = parse_display_amount(al_display)
    if fiyat_display is None or al_amt is None or fiyat_display <= 0 or al_amt <= 0:
        return None
    ratio = max(fiyat_display, al_amt) / min(fiyat_display, al_amt)
    if ratio > magnitude_ratio_max:
        return f"FİYAT/AL {ratio:.0f}× — para birimi hatası"
    dist = abs(fiyat_display / al_amt - 1.0)
    if dist > tol_pct and ratio > 2.0:
        return f"FİYAT/AL sapması %{dist * 100:.0f}"
    return None


def assert_fx_cross_sanity(
    *,
    usd_try: float,
    gbp_usd: float,
    gbp_settlement: float,
    tl_price: float,
    tol_pct: float = 2.0,
    label: str = "",
) -> float:
    """TRY/GBP (USDTRY×GBPUSD) ile TL_fiyat/GBP_fiyat oranını karşılaştırır."""
    if gbp_settlement <= 0 or tl_price <= 0:
        raise FxCrossSanityError(f"{label}: geçersiz fiyat")
    implied = try_per_gbp(usd_try, gbp_usd)
    observed = tl_price / gbp_settlement
    err_pct = abs(implied / observed - 1.0) * 100.0
    if err_pct > tol_pct:
        raise FxCrossSanityError(
            f"{label}: TRY/GBP sapması %{err_pct:.1f} "
            f"(hesap={implied:.2f} fiyat_oran={observed:.2f})"
        )
    return implied


_SETTLEMENT_PBS = frozenset({"GBP", "USD", "EUR"})


def pb_cevir(
    tutar: float,
    kaynak_pb: str,
    hedef_pb: str,
    eur_try: float,
    usd_try: float,
    *,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
) -> float:
    if kaynak_pb == hedef_pb:
        return tutar
    src, dst = kaynak_pb, hedef_pb
    if src in _SETTLEMENT_PBS and dst in _SETTLEMENT_PBS:
        from signal_engine.data.quote_normalize import convert_settlement
        return convert_settlement(
            tutar, src, dst,
            eur_try=eur_try, usd_try=usd_try,
            gbp_usd=gbp_usd, eur_usd=eur_usd,
        )
    if kaynak_pb == "TL":
        tl = tutar
    elif kaynak_pb == "EUR":
        tl = tutar * eur_try
    elif kaynak_pb == "USD":
        tl = tutar * usd_try
    elif kaynak_pb == "GBP":
        tl = tutar * try_per_gbp(usd_try, _require_gbp_usd(gbp_usd, "pb_cevir GBP→TL"))
    else:
        tl = tutar
    if hedef_pb == "TL":
        return tl
    if hedef_pb == "EUR":
        return tl / eur_try if eur_try > 0 else tutar
    if hedef_pb == "USD":
        if kaynak_pb == "GBP":
            return tutar * _require_gbp_usd(gbp_usd, "pb_cevir GBP→USD")
        if kaynak_pb == "EUR":
            return tutar * _require_eur_usd(eur_usd, "pb_cevir EUR→USD")
        return tl / usd_try if usd_try > 0 else tutar
    if hedef_pb == "GBP":
        usd_amt = pb_cevir(tutar, kaynak_pb, "USD", eur_try, usd_try, gbp_usd=gbp_usd, eur_usd=eur_usd)
        return usd_amt / _require_gbp_usd(gbp_usd, "pb_cevir →GBP")
    return tutar


def kur_al(snap) -> Tuple[float, float]:
    eur = float(getattr(getattr(snap, "veri", snap), "eur_try", None) or 35.0)
    usd = float(getattr(getattr(snap, "veri", snap), "usd_try", None) or eur * 1.08)
    return eur, usd


def kaynak_para_birimi(
    sembol: str = "",
    *,
    piyasa: str = "",
    varlik_turu: str = "",
    fon_para_birimi: str = "",
    pozisyon_turu: str = "",
    quote_currency: str = "",
) -> str:
    if quote_currency:
        from signal_engine.data.quote_normalize import normalize_price
        q = normalize_price(1.0, quote_currency)
        return q.currency
    if fon_para_birimi in GOSTERIM_PB_LIST:
        return fon_para_birimi
    if pozisyon_turu in ("nakit_eur", "nakit_usd", "nakit_ron"):
        return "TL"
    if pozisyon_turu in ("nakit_tl", "tl_mevduat", "tefas", "altin", "gumus"):
        return "TL"
    sym = (sembol or "").upper()
    if sym.endswith(".IS") or piyasa == "BIST":
        return "TL"
    if piyasa in ("SP500", "NASDAQ"):
        return "USD"
    from signal_engine.data.quote_normalize import normalize_price, resolve_quote_currency
    raw = resolve_quote_currency(sym)
    return normalize_price(1.0, raw).currency


def fiyat_donustur(
    fiyat: Optional[float],
    kaynak_pb: str,
    hedef_pb: str,
    eur_try: float,
    usd_try: float,
    *,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
) -> Optional[float]:
    if fiyat is None:
        return None
    return pb_cevir(
        float(fiyat), kaynak_pb, hedef_pb, eur_try, usd_try,
        gbp_usd=gbp_usd, eur_usd=eur_usd,
    )


def tablo_fiyat(
    fiyat: Optional[float],
    gosterim_pb: str,
    eur_try: float,
    usd_try: float,
    *,
    sembol: str = "",
    piyasa: str = "",
    varlik_turu: str = "",
    fon_para_birimi: str = "",
    kaynak_pb: str = "",
    quote_currency: str = "",
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    check_fx_sanity: bool = True,
    allow_currency_guess: bool = False,
) -> Optional[float]:
    if fiyat is None:
        return None
    from signal_engine.data.quote_normalize import coerce_settlement_amount

    if sembol:
        qc = (quote_currency or "").strip()
        kb = (kaynak_pb or "").strip()
        if not qc and kb in ("GBP", "USD", "EUR", "TRY"):
            qc = kb
        settled = coerce_settlement_amount(
            sembol, float(fiyat), qc, allow_guess=allow_currency_guess,
        )
        fiyat = settled.amount
        kaynak_pb = settled.currency
    src = kaynak_pb or kaynak_para_birimi(
        sembol, piyasa=piyasa, varlik_turu=varlik_turu, fon_para_birimi=fon_para_birimi,
        quote_currency=quote_currency,
    )
    v = fiyat_donustur(
        fiyat, src, gosterim_pb, eur_try, usd_try, gbp_usd=gbp_usd, eur_usd=eur_usd,
    )
    if v is None:
        return None
    if check_fx_sanity and src != gosterim_pb:
        assert_fx_price_cross(
            src_pb=src,
            gosterim_pb=gosterim_pb,
            src_amount=float(fiyat),
            display_amount=float(v),
            usd_try=usd_try,
            gbp_usd=gbp_usd,
            eur_usd=eur_usd,
            label=sembol or f"{src}→{gosterim_pb}",
        )
    return round(v, 4 if abs(v) < 10 else 2)


def tefas_tablo_fiyat(
    fiyat: Optional[float],
    gosterim_pb: str,
    para_birimi: str,
    eur_try: float,
    usd_try: float,
    *,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
) -> Optional[float]:
    """TEFAS birim pay fiyatı — fon adından çıkarılan PB ile gösterim PB'sine."""
    from tefas_universe import tefas_fiyat_kaynak_pb

    if fiyat is None:
        return None
    src = tefas_fiyat_kaynak_pb(para_birimi)
    if src is None:
        return None
    if src == gosterim_pb:
        return float(fiyat)
    return tablo_fiyat(
        float(fiyat), gosterim_pb, eur_try, usd_try,
        kaynak_pb=src, gbp_usd=gbp_usd, eur_usd=eur_usd,
    )


def fiyat_sutun_adi(gosterim_pb: str) -> str:
    return f"Fiyat ({gosterim_pb})"


def getiri_sutun_adi(periyot: str, gosterim_pb: str) -> str:
    return f"{periyot} ({gosterim_pb})"


def _pb_tl_katsayi(
    pb: str,
    eur_try: float,
    usd_try: float,
    *,
    gbp_usd: Optional[float] = None,
) -> float:
    if pb == "TL":
        return 1.0
    if pb == "EUR":
        return eur_try
    if pb == "USD":
        return usd_try
    if pb == "GBP":
        return try_per_gbp(usd_try, _require_gbp_usd(gbp_usd, "_pb_tl_katsayi"))
    return 1.0


def _seri_son_indis(seri: pd.Series, geri: int) -> Optional[float]:
    s = seri.dropna()
    if s.empty or len(s) <= geri:
        return None
    v = float(s.iloc[-geri - 1])
    return v if pd.notna(v) and v > 0 else None


def _fx_endpoints_for_window(
    gun: int,
    eur_s: pd.Series,
    usd_s: pd.Series,
    gbp_s: Optional[pd.Series],
    *,
    bar_dates: Optional[pd.DatetimeIndex] = None,
) -> Optional[dict]:
    """Getiri penceresi uçları — varlık bar tarihleriyle hizalı FX."""
    from fiyat_para_fx import fx_value_at, fx_window_dates

    gbp_s = gbp_s.dropna() if gbp_s is not None and not gbp_s.empty else pd.Series(dtype=float)
    if bar_dates is not None:
        pair = fx_window_dates(bar_dates, gun)
        if pair is None:
            return None
        d0, d1 = pair
        usd_start = fx_value_at(usd_s, d0)
        usd_end = fx_value_at(usd_s, d1)
        eur_start = fx_value_at(eur_s, d0)
        eur_end = fx_value_at(eur_s, d1)
        gbp_start = fx_value_at(gbp_s, d0) if not gbp_s.empty else None
        gbp_end = fx_value_at(gbp_s, d1) if not gbp_s.empty else None
    else:
        if len(eur_s.dropna()) < gun + 1:
            return None
        eur_end = float(eur_s.iloc[-1])
        eur_start = _seri_son_indis(eur_s, gun)
        usd_end = float(usd_s.iloc[-1]) if len(usd_s) else eur_end * 1.08
        usd_start = _seri_son_indis(usd_s, gun) or (eur_start * 1.08 if eur_start else None)
        gbp_end = float(gbp_s.iloc[-1]) if len(gbp_s) else None
        gbp_start = _seri_son_indis(gbp_s, gun) if len(gbp_s) else None
        d0 = usd_s.index[-gun - 1] if len(usd_s) > gun else None
        d1 = usd_s.index[-1] if len(usd_s) else None

    if eur_start is None or usd_start is None or usd_end is None or eur_end is None:
        return None
    return {
        "start_date": d0,
        "end_date": d1,
        "eur_start": eur_start,
        "eur_end": eur_end,
        "usd_start": usd_start,
        "usd_end": usd_end,
        "gbp_start": gbp_start,
        "gbp_end": gbp_end,
    }


def _resolve_bar_dates(
    bar_dates: Optional[pd.DatetimeIndex],
    asset_pb: str,
    usd_s: pd.Series,
) -> Optional[pd.DatetimeIndex]:
    """Varlık bar tarihleri yoksa: TL getirileri için FX takvimi (TEFAS vb.)."""
    if bar_dates is not None and len(bar_dates) > 0:
        return bar_dates
    usd = usd_s.dropna()
    if asset_pb == "TL" and not usd.empty:
        return pd.DatetimeIndex(usd.index)
    return None


def getiri_kur_ayarli(
    r_native_pct: Optional[float],
    asset_pb: str,
    display_pb: str,
    gun: int,
    eur_seri: pd.Series,
    usd_seri: pd.Series,
    gbp_seri: Optional[pd.Series] = None,
    *,
    bar_dates: Optional[pd.DatetimeIndex] = None,
) -> Optional[float]:
    """Varlık getirisini seçilen görüntüleme para birimine kur hareketiyle çevirir."""
    if r_native_pct is None:
        return None
    _ASSET_PB = ("EUR", "USD", "TL", "GBP")
    asset = asset_pb if asset_pb in _ASSET_PB else "TL"
    if asset == display_pb:
        return round(float(r_native_pct), 2)
    if gun <= 0:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(
            "getiri_kur_ayarli: gun<=0 cross-currency native yasak — ybb kullanın"
        )

    eur_s = eur_seri.dropna()
    usd_s = usd_seri.dropna() if usd_seri is not None and not usd_seri.empty else pd.Series(dtype=float)
    if usd_s.empty:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError("getiri_kur_ayarli: USDTRY serisi yok")
    gbp_s = gbp_seri.dropna() if gbp_seri is not None and not gbp_seri.empty else pd.Series(dtype=float)

    bar_dates = _resolve_bar_dates(bar_dates, asset, usd_s)
    if asset != display_pb and bar_dates is None:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(
            "getiri_kur_ayarli: bar_dates gerekli (FX penceresi varlık tarihleriyle hizalanmalı)"
        )

    fx = _fx_endpoints_for_window(gun, eur_s, usd_s, gbp_s, bar_dates=bar_dates)
    if fx is None:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(
            f"getiri_kur_ayarli: FX uçları yok (gun={gun}, asset={asset}→{display_pb}) "
            "— native getiriye sessiz düşmek yasak (EUR=native artefaktı)"
        )

    a_end = _pb_tl_katsayi(asset, fx["eur_end"], fx["usd_end"], gbp_usd=fx["gbp_end"])
    a_start = _pb_tl_katsayi(asset, fx["eur_start"], fx["usd_start"], gbp_usd=fx["gbp_start"])
    d_end = _pb_tl_katsayi(display_pb, fx["eur_end"], fx["usd_end"], gbp_usd=fx["gbp_end"])
    d_start = _pb_tl_katsayi(display_pb, fx["eur_start"], fx["usd_start"], gbp_usd=fx["gbp_start"])
    if a_start <= 0 or d_end <= 0:
        from fiyat_para_fx import FxUnavailableError
        raise FxUnavailableError(
            f"getiri_kur_ayarli: geçersiz FX katsayısı (a_start={a_start}, d_end={d_end})"
        )

    r = (1.0 + float(r_native_pct) / 100.0) * (a_end / a_start) * (d_start / d_end) - 1.0
    return round(r * 100.0, 2)


def getiri_kur_ayarli_ybb(
    r_native_pct: Optional[float],
    asset_pb: str,
    display_pb: str,
    eur_seri: pd.Series,
    usd_seri: pd.Series,
    gbp_seri: Optional[pd.Series] = None,
    *,
    bar_dates: Optional[pd.DatetimeIndex] = None,
) -> Optional[float]:
    """YBB getirisi — yılbaşından bugüne kur ayarlı."""
    eur_s = eur_seri.dropna()
    if eur_s.empty:
        from fiyat_para_fx import FxUnavailableError
        if r_native_pct is None:
            return None
        asset = asset_pb if asset_pb in ("EUR", "USD", "TL", "GBP") else "TL"
        if asset == display_pb:
            return round(float(r_native_pct), 2)
        raise FxUnavailableError("getiri_kur_ayarli_ybb: EURTRY serisi yok")
    idx = pd.to_datetime(eur_s.index)
    yil_basi = pd.Timestamp(date(idx[-1].year, 1, 1))
    mask = idx >= yil_basi
    if mask.sum() < 2:
        return getiri_kur_ayarli(
            r_native_pct, asset_pb, display_pb, min(180, len(eur_s) - 1),
            eur_seri, usd_seri, gbp_seri, bar_dates=bar_dates,
        )
    bas_idx = int(mask.argmax())
    gun = max(1, len(eur_s) - bas_idx - 1)
    bd = bar_dates
    if bd is not None and len(bd) > gun:
        bd = bd[-gun - 1:]
    return getiri_kur_ayarli(
        r_native_pct, asset_pb, display_pb, gun, eur_seri, usd_seri, gbp_seri, bar_dates=bd,
    )


def fx_serileri_yukle(period: str = "1y") -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    try:
        from stock_scanner import _close_al, _indir

        syms = ["EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X"]
        df = _indir(syms, period=period)
        if df.empty:
            return tuple(pd.Series(dtype=float) for _ in range(4))
        return (
            _close_al(df, "EURTRY=X"),
            _close_al(df, "USDTRY=X"),
            _close_al(df, "GBPUSD=X"),
            _close_al(df, "EURUSD=X"),
        )
    except Exception:
        return tuple(pd.Series(dtype=float) for _ in range(4))


def fx_serileri_al(tarama=None) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    eur = getattr(tarama, "eurtry_seri", None) if tarama is not None else None
    usd = getattr(tarama, "usdtry_seri", None) if tarama is not None else None
    gbp = getattr(tarama, "gbpusd_seri", None) if tarama is not None else None
    eurusd = getattr(tarama, "eurusd_seri", None) if tarama is not None else None
    if (
        eur is not None and not eur.empty
        and usd is not None and not usd.empty
        and gbp is not None and not gbp.empty
    ):
        if eurusd is None or eurusd.empty:
            eurusd = pd.Series(dtype=float)
        return eur, usd, gbp, eurusd
    cache = st.session_state.get("_fx_serileri_cache")
    if cache and len(cache) >= 3 and not cache[0].empty and not cache[1].empty and not cache[2].empty:
        eurusd_c = cache[3] if len(cache) >= 4 else pd.Series(dtype=float)
        return cache[0], cache[1], cache[2], eurusd_c
    eur, usd, gbp, eurusd = fx_serileri_yukle()
    st.session_state["_fx_serileri_cache"] = (eur, usd, gbp, eurusd)
    return eur, usd, gbp, eurusd


def _fx_spot_snap_fallback(snap) -> "FxSpot":
    """Yahoo serisi yokken UI düşmesin — SNAP kurları (uyarı ile kullanılmalı)."""
    from fiyat_para_fx import FxSpot

    e, u = kur_al(snap)
    v = getattr(snap, "veri", snap)
    eur_usd = getattr(v, "eur_usd", None) or getattr(snap, "eur_usd", None)
    try:
        eur_usd_f = float(eur_usd) if eur_usd else (float(e) / float(u) if u else 1.08)
    except (TypeError, ValueError):
        eur_usd_f = float(e) / float(u) if u else 1.08
    # SNAP'ta GBP yok — makul orta bant
    gbp_usd_f = 1.30
    return FxSpot(
        eur_try=float(e),
        usd_try=float(u),
        gbp_usd=gbp_usd_f,
        eur_usd=eur_usd_f,
        asof=str(date.today()),
        source="SNAP fallback (Yahoo USDTRY yok)",
    )


def tablo_fx_hazirla(snap, tarama=None, *, allow_snap_fallback: bool = False):
    """
    Tablo için Yahoo FX + guard — (FxSpot, seriler).
    allow_snap_fallback=True: Yahoo serisi yoksa SNAP ile devam (UI crash olmasın).
    """
    from fiyat_para_fx import FxUnavailableError, assert_fx_snap_vs_series, kur_tablo_spot

    eur_s, usd_s, gbp_s, eurusd_s = fx_serileri_al(tarama)
    if usd_s is None or getattr(usd_s, "empty", True):
        # Bozuk session cache — bir kez yeniden indir
        try:
            import streamlit as st

            st.session_state.pop("_fx_serileri_cache", None)
        except Exception:
            pass
        eur_s, usd_s, gbp_s, eurusd_s = fx_serileri_yukle()
        try:
            import streamlit as st

            st.session_state["_fx_serileri_cache"] = (eur_s, usd_s, gbp_s, eurusd_s)
        except Exception:
            pass

    try:
        assert_fx_snap_vs_series(snap, eur_s, usd_s, gbp_s, eurusd_s)
        fx = kur_tablo_spot(snap, eur_s, usd_s, gbp_s, eurusd_s)
        return fx, eur_s, usd_s, gbp_s, eurusd_s
    except FxUnavailableError:
        if not allow_snap_fallback:
            raise
        empty = pd.Series(dtype=float)
        return (
            _fx_spot_snap_fallback(snap),
            eur_s if eur_s is not None else empty,
            usd_s if usd_s is not None else empty,
            gbp_s if gbp_s is not None else empty,
            eurusd_s if eurusd_s is not None else empty,
        )


def tablo_getiri(
    r_native_pct: Optional[float],
    gosterim_pb: str,
    gun: int,
    eur_seri: pd.Series,
    usd_seri: pd.Series,
    *,
    sembol: str = "",
    piyasa: str = "",
    varlik_turu: str = "",
    asset_pb: str = "",
    quote_currency: str = "",
    ybb: bool = False,
    gbp_seri: Optional[pd.Series] = None,
    bar_dates: Optional[pd.DatetimeIndex] = None,
) -> Optional[float]:
    src = asset_pb or kaynak_para_birimi(
        sembol, piyasa=piyasa, varlik_turu=varlik_turu, quote_currency=quote_currency,
    )
    usd_clean = usd_seri.dropna() if usd_seri is not None else pd.Series(dtype=float)
    bd = _resolve_bar_dates(bar_dates, src, usd_clean)
    if ybb:
        return getiri_kur_ayarli_ybb(
            r_native_pct, src, gosterim_pb, eur_seri, usd_seri, gbp_seri, bar_dates=bd,
        )
    return getiri_kur_ayarli(
        r_native_pct, src, gosterim_pb, gun, eur_seri, usd_seri, gbp_seri, bar_dates=bd,
    )


def tutar_fmt(tutar: float, pb: str) -> str:
    return f"{tutar:,.0f} {pb}"


def tutar_goster(
    tutar: float,
    kaynak_pb: str,
    gosterim_pb: str,
    eur_try: float,
    usd_try: float,
    *,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
) -> str:
    v = pb_cevir(
        float(tutar), kaynak_pb, gosterim_pb, eur_try, usd_try,
        gbp_usd=gbp_usd, eur_usd=eur_usd,
    )
    return tutar_fmt(v, gosterim_pb)


def session_gosterim_pb() -> str:
    pb = st.session_state.get("gosterim_pb", "EUR")
    return pb if pb in GOSTERIM_PB_LIST else "EUR"


def sidebar_gosterim_pb_secici() -> str:
    if "gosterim_pb" not in st.session_state:
        store = st.session_state.get("varlik_store")
        baslangic = getattr(store, "goruntuleme_pb", "EUR") if store else "EUR"
        st.session_state.gosterim_pb = baslangic if baslangic in GOSTERIM_PB_LIST else "EUR"
    idx = GOSTERIM_PB_LIST.index(session_gosterim_pb())
    pb = st.selectbox(
        "Tablo fiyat birimi",
        GOSTERIM_PB_LIST,
        index=idx,
        help="Hisse, ETF, endeks ve fon tablolarındaki fiyat ve getiri % bu para biriminde gösterilir (kur etkisi dahil).",
        key="sidebar_gosterim_pb",
    )
    st.session_state.gosterim_pb = pb
    store = st.session_state.get("varlik_store")
    if store is not None and getattr(store, "goruntuleme_pb", pb) != pb:
        store.goruntuleme_pb = pb
    return pb


from fiyat_para_fx import (  # noqa: E402
    FxSanityError,
    FxSpot,
    FxUnavailableError,
    assert_fx_snap_vs_series,
    kur_tablo_spot,
)
