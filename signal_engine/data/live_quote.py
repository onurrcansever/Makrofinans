# -*- coding: utf-8 -*-
"""Canlı kotasyon — yfinance fast_info ile taze fiyat + zaman damgası."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from signal_engine.data.quote_normalize import normalize_price, resolve_quote_currency


@dataclass
class LiveQuote:
    price: float
    currency: str
    settlement: str
    timestamp: datetime
    age_min: float


_cache: Dict[str, LiveQuote] = {}
_fetched_at: float = 0.0


def _ts_from_unix(raw) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        v = float(raw)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _fetch_one(symbol: str) -> Optional[LiveQuote]:
    sym = (symbol or "").strip()
    if not sym:
        return None
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        fi = getattr(t, "fast_info", None) or {}
        price = fi.get("lastPrice") or fi.get("regularMarketPrice")
        if price is None:
            info = t.info or {}
            price = info.get("regularMarketPrice") or info.get("previousClose")
        if price is None:
            return None
        raw_ccy = (
            fi.get("currency")
            or (t.info or {}).get("currency")
            or resolve_quote_currency(sym)
        )
        ts = _ts_from_unix(
            fi.get("regularMarketTime")
            or fi.get("postMarketTime")
            or fi.get("preMarketTime")
        )
        if ts is None:
            ts = datetime.now(timezone.utc)
        settled = normalize_price(float(price), str(raw_ccy))
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - ts).total_seconds() / 60.0)
        return LiveQuote(
            price=settled.amount,
            currency=str(raw_ccy),
            settlement=settled.currency,
            timestamp=ts,
            age_min=age,
        )
    except Exception:
        return None


def refresh_live_quotes(
    symbols: Iterable[str],
    *,
    force: bool = False,
    max_workers: int = 12,
    min_refresh_sec: float = 60.0,
) -> None:
    """Sembol listesi için canlı kotasyon önbelleğini güncelle."""
    global _fetched_at
    now = time.time()
    if not force and _cache and (now - _fetched_at) < min_refresh_sec:
        return
    uniq = list(dict.fromkeys(s.upper() for s in symbols if s))
    if not uniq:
        return
    out: Dict[str, LiveQuote] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in uniq}
        for fut in as_completed(futs, timeout=45):
            sym = futs[fut]
            try:
                q = fut.result()
                if q:
                    out[sym] = q
            except Exception:
                pass
    _cache.clear()
    _cache.update(out)
    _fetched_at = now


def get_live_quote(symbol: str) -> Optional[LiveQuote]:
    return _cache.get((symbol or "").upper())


def clear_live_quote_cache() -> None:
    global _fetched_at
    _cache.clear()
    _fetched_at = 0.0


def quote_age_from_bar(ts, piyasa: str) -> Optional[float]:
    """Günlük bar indeksinden yaş — gece yarısı UTC yerine seans saati."""
    from datetime import timedelta

    try:
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    if dt.hour == 0 and dt.minute == 0:
        if piyasa == "BIST":
            open_h, close_h = 7, 15
        elif piyasa in ("SP500", "NASDAQ", "ETF"):
            open_h, close_h = 13, 20
        else:
            open_h, close_h = 13, 20
        close_dt = dt + timedelta(hours=close_h)
        open_dt = dt + timedelta(hours=open_h)
        if close_dt > now:
            # Seans devam — açılıştan bu yana
            ref = open_dt if open_dt <= now else dt
            return max(0.0, (now - ref).total_seconds() / 60.0)
        dt = close_dt
        if dt > now:
            dt -= timedelta(days=1)

    return max(0.0, (now - dt).total_seconds() / 60.0)
