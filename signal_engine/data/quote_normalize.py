# -*- coding: utf-8 -*-
"""Quote normalization — GBX/pence, sanity gate, quarantine."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import yaml

_log = logging.getLogger(__name__)

_LISTING_PATH = Path(__file__).resolve().parent / "listing_currency.yaml"
_LISTING_CACHE: Optional[dict] = None

# Yahoo GBp kotasyonları genelde ≥500 pence; zaten GBP olan LSE ETF'ler ~5–500 aralığında.
PENCE_THRESHOLD = 500.0
LSE_ETF_GBP_MIN = 5.0
LSE_ETF_GBP_MAX = 5000.0


class MissingQuoteCurrencyError(ValueError):
    """quote_currency zorunlu — sessiz suffix/PENCE_THRESHOLD tahmini kapalı."""


_SETTLEMENT_CCYS = frozenset({"GBP", "USD", "EUR", "TRY", "CHF"})


@dataclass
class NormalizedQuote:
    amount: float
    currency: str  # ISO-like: GBP, USD, EUR, TRY
    already_settled: bool = False


@dataclass
class SeriesQuoteMeta:
    symbol: str
    quote_currency_raw: str
    settlement_currency: str
    quarantine: bool = False
    quarantine_reason: str = ""
    median_ratio: Optional[float] = None


def _load_listing() -> dict:
    global _LISTING_CACHE
    if _LISTING_CACHE is None:
        raw = yaml.safe_load(_LISTING_PATH.read_text(encoding="utf-8")) or {}
        _LISTING_CACHE = {str(k).upper(): str(v) for k, v in raw.items()}
    return _LISTING_CACHE


def _canonical_quote_currency(currency: str) -> str:
    c = (currency or "").strip()
    if not c:
        return ""
    # GBp önce — "GBp".upper() == "GBP" tuzağı
    if c == "GBp" or c.upper() == "GBX":
        return "GBp"
    if c == "GBP" or c.upper() == "GBP":
        return "GBP"
    return c.upper()


def _is_pence(currency: str) -> bool:
    return _canonical_quote_currency(currency) == "GBp"


def _looks_like_pence_amount(amount: float) -> bool:
    return float(amount) >= PENCE_THRESHOLD


def resolve_quote_currency(symbol: str, source_currency: Optional[str] = None) -> str:
    """Quote currency — önce kaynak (yfinance `currency`), sonra yaml, sonra suffix."""
    if source_currency:
        return _canonical_quote_currency(source_currency)
    sym = (symbol or "").upper()
    mapped = _load_listing().get(sym)
    if mapped:
        return _canonical_quote_currency(mapped)
    if sym.endswith(".IS"):
        return "TRY"
    if sym.endswith(".SW"):
        return "CHF"
    if sym.endswith((".DE", ".AS", ".PA", ".MI")):
        return "EUR"
    if sym.endswith((".L", ".LON")):
        return "GBp"
    if sym.endswith((".US",)) or sym.isalpha() and "." not in sym:
        return "USD"
    return "USD"


@lru_cache(maxsize=256)
def fetch_source_quote_currency(symbol: str) -> str:
    """yfinance listing currency (GBP vs GBp) — ingestion için."""
    sym = (symbol or "").strip()
    if not sym:
        return ""
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        c = None
        try:
            fi = t.fast_info
            c = fi.get("currency") if fi else None
        except Exception:
            pass
        if not c:
            c = (t.info or {}).get("currency")
        return _canonical_quote_currency(c) if c else ""
    except Exception:
        return ""


def normalize_price(amount: float, quote_currency: str, *, guess: bool = False) -> NormalizedQuote:
    """
    Idempotent settlement dönüşümü.
    GBp: Yahoo/kaynak alanı yetkiliyse her zaman /100; guess=True ise eşik (≥500) uygulanır.
    """
    if amount is None or (isinstance(amount, float) and pd.isna(amount)):
        raise ValueError("amount required")
    qc = _canonical_quote_currency(quote_currency or "USD")
    amt = float(amount)
    if qc == "GBP":
        return NormalizedQuote(amt, "GBP", already_settled=True)
    if _is_pence(qc):
        if guess and not _looks_like_pence_amount(amt):
            return NormalizedQuote(amt, "GBP", already_settled=True)
        return NormalizedQuote(amt / 100.0, "GBP", already_settled=True)
    return NormalizedQuote(amt, qc, already_settled=qc in _SETTLEMENT_CCYS)


def _resolve_guess_currency(symbol: str) -> str:
    """Yahoo currency alanı öncelikli; yoksa yaml/suffix."""
    yahoo = fetch_source_quote_currency(symbol)
    if yahoo:
        return yahoo
    return resolve_quote_currency(symbol)


def coerce_settlement_amount(
    symbol: str,
    amount: float,
    quote_currency: str = "",
    *,
    allow_guess: bool = False,
) -> NormalizedQuote:
    """
    Ham veya settlement fiyat → GBP/USD/EUR birimi.
    quote_currency yoksa ValueError (allow_guess=True ile Yahoo/suffix + WARN).
    Settlement GBP/USD/EUR/TRY ise idempotent — tekrar /100 yapılmaz.
    """
    qc_raw = (quote_currency or "").strip()
    if qc_raw:
        canon = _canonical_quote_currency(qc_raw)
        if _is_pence(canon):
            return normalize_price(float(amount), "GBp", guess=False)
        if canon == "GBP":
            return NormalizedQuote(float(amount), "GBP", already_settled=True)
        if canon in _SETTLEMENT_CCYS:
            return NormalizedQuote(float(amount), canon, already_settled=True)
        return normalize_price(float(amount), qc_raw)

    if not allow_guess:
        raise MissingQuoteCurrencyError(
            f"coerce_settlement_amount({symbol!r}): quote_currency zorunlu "
            f"(allow_guess=True ile Yahoo currency denenebilir)"
        )

    raw_ccy = _resolve_guess_currency(symbol)
    if fetch_source_quote_currency(symbol):
        _log.warning(
            "coerce_settlement_amount: quote_currency yok, Yahoo currency=%s (%s)",
            raw_ccy,
            symbol,
        )
    else:
        _log.warning(
            "coerce_settlement_amount: quote_currency yok, suffix tahmini=%s (%s)",
            raw_ccy,
            symbol,
        )
    return normalize_price(float(amount), raw_ccy, guess=True)


def sanity_check_vs_median(
    normalized_close: pd.Series,
    *,
    ratio_hi: float = 5.0,
    ratio_lo: float = 0.2,
    min_bars: int = 60,
) -> Tuple[bool, str, Optional[float]]:
    """Son fiyatı 200g medyana göre kontrol et."""
    s = normalized_close.dropna()
    if len(s) < min_bars:
        return True, "", None
    med = float(s.tail(200).median())
    last = float(s.iloc[-1])
    if med <= 0 or last <= 0:
        return False, "VERİ HATASI: sıfır/negatif fiyat", None
    ratio = last / med
    if ratio > ratio_hi or ratio < ratio_lo:
        return (
            False,
            f"VERİ HATASI: fiyat medyanın {ratio:.1f}× sapması (200g medyan {med:.2f})",
            ratio,
        )
    return True, "", ratio


def sanity_check_lse_magnitude(
    symbol: str,
    normalized_close: pd.Series,
    *,
    min_gbp: float = LSE_ETF_GBP_MIN,
    max_gbp: float = LSE_ETF_GBP_MAX,
    min_bars: int = 30,
) -> Tuple[bool, str]:
    """LSE UCITS için settlement büyüklük bandı — çifte GBX dönüşümünü yakalar."""
    sym = (symbol or "").upper()
    if not sym.endswith(".L"):
        return True, ""
    s = normalized_close.dropna()
    if len(s) < min_bars:
        return True, ""
    med = float(s.tail(min(200, len(s))).median())
    if med < min_gbp:
        return (
            False,
            f"VERİ HATASI: {sym} medyan {med:.2f} GBP — olası çifte GBX dönüşümü",
        )
    if med > max_gbp:
        return (
            False,
            f"VERİ HATASI: {sym} medyan {med:.2f} GBP — olası pence (GBX) hatası",
        )
    return True, ""


def _series_to_settlement(
    symbol: str,
    close: pd.Series,
    quote_currency: str,
    *,
    guess: bool = False,
) -> Tuple[pd.Series, str]:
    """Tek seferlik seri dönüşümü — kaynak para birimine göre."""
    s = close.dropna().astype(float)
    qc = _canonical_quote_currency(quote_currency)
    med = float(s.tail(min(200, len(s))).median()) if len(s) else 0.0

    if qc == "GBP":
        return s.copy(), "GBP"
    if _is_pence(qc):
        if guess and med < PENCE_THRESHOLD:
            return s.copy(), "GBP"
        return s / 100.0, "GBP"
    settle = qc
    return s.copy(), settle


def normalize_close_series(
    symbol: str,
    close: pd.Series,
    *,
    source_currency: Optional[str] = None,
) -> Tuple[pd.Series, SeriesQuoteMeta]:
    """Normalize full close series; sanity + magnitude gate on latest bar."""
    sym = symbol or ""
    guess = source_currency is None
    raw_ccy = resolve_quote_currency(sym, source_currency)
    s = close.dropna().astype(float)
    if s.empty:
        return s, SeriesQuoteMeta(sym, raw_ccy, raw_ccy, quarantine=True, quarantine_reason="boş seri")

    norm, settle = _series_to_settlement(sym, s, raw_ccy, guess=guess)

    ok_med, reason_med, ratio = sanity_check_vs_median(norm)
    ok_mag, reason_mag = sanity_check_lse_magnitude(sym, norm)
    ok = ok_med and ok_mag
    reason = reason_med or reason_mag

    meta = SeriesQuoteMeta(
        symbol=sym,
        quote_currency_raw=raw_ccy,
        settlement_currency=settle,
        quarantine=not ok,
        quarantine_reason=reason,
        median_ratio=ratio,
    )
    return norm, meta


def _to_usd_bridge(
    amount: float,
    currency: str,
    *,
    usd_try: float,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    chf_usd: Optional[float] = None,
) -> float:
    from fiyat_para_fx import FxUnavailableError

    c = (currency or "USD").upper()
    if c == "USD":
        return amount
    if c == "GBP":
        if gbp_usd is None or gbp_usd <= 0:
            raise FxUnavailableError("GBPUSD gerekli (convert_settlement)")
        return amount * gbp_usd
    if c == "EUR":
        if eur_usd is None or eur_usd <= 0:
            raise FxUnavailableError("EURUSD gerekli (convert_settlement)")
        return amount * eur_usd
    if c == "CHF":
        if chf_usd is None or chf_usd <= 0:
            raise FxUnavailableError("CHFUSD gerekli (convert_settlement)")
        return amount * chf_usd
    if c == "TRY":
        if usd_try <= 0:
            raise FxUnavailableError("USDTRY gerekli")
        return amount / usd_try
    return amount


def _from_usd_bridge(
    usd: float,
    currency: str,
    *,
    usd_try: float,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    chf_usd: Optional[float] = None,
) -> float:
    from fiyat_para_fx import FxUnavailableError

    c = (currency or "USD").upper()
    if c == "USD":
        return usd
    if c == "GBP":
        if gbp_usd is None or gbp_usd <= 0:
            raise FxUnavailableError("GBPUSD gerekli (convert_settlement)")
        return usd / gbp_usd
    if c == "EUR":
        if eur_usd is None or eur_usd <= 0:
            raise FxUnavailableError("EURUSD gerekli (convert_settlement)")
        return usd / eur_usd
    if c == "CHF":
        if chf_usd is None or chf_usd <= 0:
            raise FxUnavailableError("CHFUSD gerekli (convert_settlement)")
        return usd / chf_usd
    if c == "TRY":
        return usd * usd_try
    return usd


def convert_settlement(
    amount: float,
    from_currency: str,
    to_currency: str,
    *,
    eur_try: float,
    usd_try: float,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    chf_usd: Optional[float] = None,
) -> float:
    """Settlement para birimleri arası dönüşüm (faktör/giriş seviyesi hattı)."""
    fc = (from_currency or "USD").upper()
    tc = (to_currency or "USD").upper()
    if fc == tc:
        return amount
    # EURUSD yoksa EURTRY÷USDTRY (Yahoo çaprazı gecikmeli/eksik olabilir)
    if (eur_usd is None or eur_usd <= 0) and eur_try > 0 and usd_try > 0:
        eur_usd = float(eur_try) / float(usd_try)
    kw = dict(usd_try=usd_try, gbp_usd=gbp_usd, eur_usd=eur_usd, chf_usd=chf_usd)
    usd = _to_usd_bridge(amount, fc, **kw)
    return _from_usd_bridge(usd, tc, **kw)


def to_display_currency(
    amount: float,
    from_currency: str,
    display: str,
    *,
    eur_try: float,
    usd_try: float,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    chf_usd: Optional[float] = None,
) -> float:
    """FX to display currency (dated rates from caller)."""
    return convert_settlement(
        amount, from_currency, display,
        eur_try=eur_try, usd_try=usd_try, gbp_usd=gbp_usd, eur_usd=eur_usd,
        chf_usd=chf_usd,
    )
