# -*- coding: utf-8 -*-
"""Canlı kotasyon — yfinance fast_info; bellek + disk (≤15 dk)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from signal_engine.data.quote_normalize import normalize_price, resolve_quote_currency

# Disk önbellek — tarama TTL ile aynı üst sınır (15 dk)
DISK_TTL_SEC = 15 * 60

_DISK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".live_quotes_cache.json",
)


@dataclass
class LiveQuote:
    price: float
    currency: str
    settlement: str
    timestamp: datetime
    age_min: float
    previous_close: Optional[float] = None
    cached_at: Optional[float] = None  # unix — disk yazım anı


_cache: Dict[str, LiveQuote] = {}
_fetched_at: float = 0.0


def live_quotes_disk_path() -> str:
    return os.getenv("LIVE_QUOTES_CACHE", _DISK_PATH)


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


def _quote_to_dict(q: LiveQuote) -> dict:
    return {
        "price": q.price,
        "currency": q.currency,
        "settlement": q.settlement,
        "timestamp": q.timestamp.isoformat(),
        "previous_close": q.previous_close,
        "cached_at": q.cached_at if q.cached_at is not None else time.time(),
    }


def _quote_from_dict(d: dict) -> Optional[LiveQuote]:
    try:
        price = float(d["price"])
        if price <= 0:
            return None
        ts_raw = d.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
        cached_at = d.get("cached_at")
        if cached_at is not None:
            cached_at = float(cached_at)
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - ts).total_seconds() / 60.0)
        prev = d.get("previous_close")
        return LiveQuote(
            price=price,
            currency=str(d.get("currency") or ""),
            settlement=str(d.get("settlement") or d.get("currency") or ""),
            timestamp=ts,
            age_min=age,
            previous_close=float(prev) if prev is not None else None,
            cached_at=cached_at,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _quote_fresh(q: LiveQuote, *, now: Optional[float] = None, ttl_sec: float = DISK_TTL_SEC) -> bool:
    ref = now if now is not None else time.time()
    if q.cached_at is not None:
        return (ref - float(q.cached_at)) <= ttl_sec
    # cached_at yoksa market timestamp'e bak
    return (ref - q.timestamp.timestamp()) <= ttl_sec


def save_live_quotes_disk(quotes: Optional[Dict[str, LiveQuote]] = None) -> None:
    """Bellekteki (veya verilen) kotasyonları diske yaz."""
    src = quotes if quotes is not None else _cache
    if not src:
        return
    now = time.time()
    payload = {
        "fetched_at": _fetched_at or now,
        "quotes": {},
    }
    for sym, q in src.items():
        if q.cached_at is None:
            q.cached_at = now
        payload["quotes"][sym] = _quote_to_dict(q)
    path = live_quotes_disk_path()
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".live_quotes.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass


def load_live_quotes_disk(
    *,
    ttl_sec: float = DISK_TTL_SEC,
    hydrate_memory: bool = False,
) -> Dict[str, LiveQuote]:
    """Diskten kotasyonları oku. ttl_sec çok büyükse bayat kabul (SWR)."""
    path = live_quotes_disk_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    now = time.time()
    out: Dict[str, LiveQuote] = {}
    for sym, d in (raw.get("quotes") or {}).items():
        if not isinstance(d, dict):
            continue
        q = _quote_from_dict(d)
        if q is None or not _quote_fresh(q, now=now, ttl_sec=ttl_sec):
            continue
        out[str(sym).upper()] = q
    if hydrate_memory and out:
        _cache.update(out)
    return out


def get_live_quote(symbol: str, *, allow_stale: bool = False) -> Optional[LiveQuote]:
    """allow_stale: TTL geçmiş disk/bellek kotasyonunu da kullan (1G previousClose SWR)."""
    sym = (symbol or "").upper()
    mem = _cache.get(sym)
    if mem is not None and _quote_fresh(mem):
        return mem
    ttl = (48 * 3600.0) if allow_stale else DISK_TTL_SEC
    disk = load_live_quotes_disk(ttl_sec=ttl, hydrate_memory=False)
    q = disk.get(sym)
    if q is not None:
        _cache[sym] = q
        return q
    if allow_stale and mem is not None:
        return mem
    return None


def clear_live_quote_cache(*, keep_disk: bool = False) -> None:
    """Belleği temizle. keep_disk=True: son kayıt diskte kalsın (Şimdi yenile SWR)."""
    global _fetched_at
    _cache.clear()
    _fetched_at = 0.0
    if keep_disk:
        return
    path = live_quotes_disk_path()
    try:
        os.unlink(path)
    except OSError:
        pass


def live_quotes_cache_age_sec() -> Optional[float]:
    """Disk önbelleğinin yaşı (sn); yoksa None."""
    path = live_quotes_disk_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        fa = raw.get("fetched_at")
        if fa is not None:
            return max(0.0, time.time() - float(fa))
        return max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        try:
            return max(0.0, time.time() - os.path.getmtime(path))
        except OSError:
            return None


def _fi_get(fi, *keys):
    for k in keys:
        if hasattr(fi, "get"):
            v = fi.get(k)
        else:
            v = getattr(fi, k, None)
        if v is not None:
            try:
                if float(v) > 0:
                    return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _resolve_previous_close(t, fi, price: float) -> Optional[float]:
    """Resmi önceki seans kapanışı (Google Önc. kpş. / Yahoo regularMarketPreviousClose).

    fast_info.previousClose bazen yanlış (CSCO: 110 yerine 111.77) — önce bitişik
    günlük mum, sonra info, en son fast_info.
    """
    import pandas as pd

    # 1) Bitişik günlük mumlar (gap ≤ 2 gün)
    try:
        hist = t.history(period="10d", auto_adjust=False)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            c = hist["Close"].dropna()
            if len(c) >= 2:
                d0 = pd.Timestamp(c.index[-2]).tz_localize(None).normalize()
                d1 = pd.Timestamp(c.index[-1]).tz_localize(None).normalize()
                gap = abs((d1 - d0).days)
                last_c = float(c.iloc[-1])
                prev_c = float(c.iloc[-2])
                if gap <= 2 and prev_c > 0 and last_c > 0:
                    # Canlı ≈ son mum → önceki seans = bir önceki mum
                    if abs(float(price) - last_c) / max(abs(last_c), 1e-9) < 0.02:
                        return prev_c
                    # Premarket / yeni seans: son tamamlanan mum = önceki kapanış
                    return last_c
    except Exception:
        pass

    # 2) info — Google/Yahoo ile aynı alan (fast_info'tan güvenilir)
    try:
        info = t.info or {}
        for k in ("regularMarketPreviousClose", "previousClose"):
            v = info.get(k)
            if v is not None and float(v) > 0:
                return float(v)
    except Exception:
        pass

    # 3) fast_info son çare
    return _fi_get(fi, "regularMarketPreviousClose", "previousClose")


def _fetch_one(symbol: str) -> Optional[LiveQuote]:
    sym = (symbol or "").strip()
    if not sym:
        return None
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        fi = getattr(t, "fast_info", None) or {}
        info = None
        price = _fi_get(fi, "lastPrice", "regularMarketPrice")
        if price is None:
            info = t.info or {}
            for k in ("regularMarketPrice", "currentPrice", "lastPrice"):
                v = info.get(k)
                if v is not None and float(v) > 0:
                    price = float(v)
                    break
        if price is None:
            return None

        prev = _resolve_previous_close(t, fi, float(price))

        raw_ccy = (
            (fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None))
            or (info or {}).get("currency")
            or resolve_quote_currency(sym)
        )
        ts = None
        if hasattr(fi, "get"):
            ts = _ts_from_unix(
                fi.get("regularMarketTime")
                or fi.get("postMarketTime")
                or fi.get("preMarketTime")
            )
        if ts is None:
            ts = datetime.now(timezone.utc)
        settled = normalize_price(float(price), str(raw_ccy))
        prev_amt = None
        if prev is not None:
            try:
                prev_amt = normalize_price(float(prev), str(raw_ccy)).amount
            except (TypeError, ValueError):
                prev_amt = None
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - ts).total_seconds() / 60.0)
        return LiveQuote(
            price=settled.amount,
            currency=str(raw_ccy),
            settlement=settled.currency,
            timestamp=ts,
            age_min=age,
            previous_close=prev_amt,
            cached_at=time.time(),
        )
    except Exception:
        return None


def refresh_live_quotes(
    symbols: Iterable[str],
    *,
    force: bool = False,
    max_workers: int = 12,
    min_refresh_sec: float = 60.0,
    persist: bool = True,
) -> None:
    """Sembol listesi için canlı kotasyon önbelleğini güncelle (+ disk)."""
    global _fetched_at
    now = time.time()
    if not force and _cache and (now - _fetched_at) < min_refresh_sec:
        return
    uniq = list(dict.fromkeys(s.upper() for s in symbols if s))
    if not uniq:
        return
    out: Dict[str, LiveQuote] = {}
    workers = max(1, min(int(max_workers), len(uniq)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in uniq}
        try:
            for fut in as_completed(futs, timeout=45):
                sym = futs[fut]
                try:
                    q = fut.result()
                    if q:
                        out[sym] = q
                except Exception:
                    pass
        except TimeoutError:
            pass
    if out:
        _cache.clear()
        _cache.update(out)
        _fetched_at = now
        if persist:
            save_live_quotes_disk(out)
    elif persist and _cache:
        save_live_quotes_disk(_cache)


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
            ref = open_dt if open_dt <= now else dt
            return max(0.0, (now - ref).total_seconds() / 60.0)
        dt = close_dt
        if dt > now:
            dt -= timedelta(days=1)

    return max(0.0, (now - dt).total_seconds() / 60.0)
