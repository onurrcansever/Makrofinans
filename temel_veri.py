# -*- coding: utf-8 -*-
"""
Temel veri katmanı — Yahoo .info + finansal özet (ciro, FCF, bilanço).
Analist/F/K: Momentum / Neden? paneli.
Finans özeti: Signal Engine fund_gate ile AL kararını kesebilir.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# progress_cb(done, total, mesaj) — UI progress bar için
ProgressCb = Optional[Callable[[int, int, str], None]]

_log = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(_ROOT, ".temel_veri_cache.json")
CI_SYNC_PATH = os.path.join(_ROOT, "data", "ci_temel_veri_cache.json")


def _cache_kaynak_yolu() -> Optional[str]:
    for path in (STATE_PATH, CI_SYNC_PATH):
        if os.path.isfile(path):
            return path
    return None

INFO_ALANLAR = (
    "trailingPE",
    "forwardPE",
    "earningsGrowth",
    "revenueGrowth",
    "recommendationKey",
    "numberOfAnalystOpinions",
    "targetMeanPrice",
    "currentPrice",
    "regularMarketPrice",
    "currency",
    "profitMargins",
)

TTL_HOURS = 24
# Yahoo oturumları FD tüketir — yüksek paralellik Errno 24 (too many open files)
MAX_WORKERS = 3
SYMBOL_TIMEOUT_SEC = 8.0  # .info + rec + financials
FINANS_TTL_HOURS = 48  # bilanço daha seyrek değişir

_cache_io_lock = threading.Lock()

_ANALIST_TR = {
    "strong_buy": "Güçlü Al",
    "buy": "Al",
    "hold": "Tut",
    "sell": "Sat",
    "strong_sell": "Güçlü Sat",
}


def _bugun() -> str:
    return date.today().isoformat()


def _parse_gun(s: str) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _cache_taze(entry: dict, *, now: Optional[date] = None) -> bool:
    g = _parse_gun(entry.get("guncelleme", ""))
    if g is None:
        return False
    ref = now or date.today()
    # guncelleme gün başı; 24 saat = ertesi takvim gününe kadar taze
    return (ref - g) < timedelta(hours=TTL_HOURS)


_yukle_mem: Optional[Dict[str, dict]] = None
_yukle_mtime: Optional[float] = None


def yukle_cache() -> Dict[str, dict]:
    """Disk cache — aynı process'te mtime ile kısa bellek (tablo satırları için)."""
    global _yukle_mem, _yukle_mtime
    kaynak = _cache_kaynak_yolu()
    if not kaynak:
        _yukle_mem, _yukle_mtime = {}, None
        return {}
    try:
        mtime = os.path.getmtime(kaynak)
        if _yukle_mem is not None and _yukle_mtime == mtime:
            return _yukle_mem
        with open(kaynak, encoding="utf-8") as f:
            raw = json.load(f)
        out = raw if isinstance(raw, dict) else {}
        _yukle_mem, _yukle_mtime = out, mtime
        return out
    except Exception as e:
        _log.warning("temel_veri cache okunamadı: %s", e)
        return {}


def _cleanup_cache_tmps() -> None:
    """Yarım kalmış .temel_veri.*.tmp dosyalarını sil (FD / disk sızıntısı)."""
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    try:
        for name in os.listdir(directory):
            if name.startswith(".temel_veri.") and name.endswith(".tmp"):
                path = os.path.join(directory, name)
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def kaydet_cache(cache: Dict[str, dict]) -> bool:
    """Atomik yazma — tmp + os.replace. FD tükenirse False (çekim devam eder)."""
    global _yukle_mem, _yukle_mtime
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    with _cache_io_lock:
        for attempt in range(2):
            tmp = ""
            fd = -1
            try:
                fd, tmp = tempfile.mkstemp(
                    prefix=".temel_veri.", suffix=".tmp", dir=directory,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    fd = -1  # fdopen sahiplendi
                    json.dump(cache, f, ensure_ascii=False, indent=2)
                os.replace(tmp, STATE_PATH)
                tmp = ""
                _yukle_mem, _yukle_mtime = cache, os.path.getmtime(STATE_PATH)
                return True
            except OSError as e:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                if getattr(e, "errno", None) == 24 and attempt == 0:
                    _log.warning("temel_veri kaydet: FD tükenmiş, temizlik + yeniden dene")
                    _cleanup_cache_tmps()
                    time.sleep(0.35)
                    continue
                _log.warning("temel_veri kaydet başarısız: %s", e)
                return False
            except Exception as e:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                _log.warning("temel_veri kaydet hata: %s", e)
                return False
        return False


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def _df_cell(df, row_names: tuple, col_idx: int = 0) -> Optional[float]:
    """Yahoo financials DataFrame — satır adı esnek eşleşme."""
    if df is None or getattr(df, "empty", True):
        return None
    try:
        idx_l = {str(i).strip().lower(): i for i in df.index}
    except Exception:
        return None
    for name in row_names:
        key = name.lower()
        if key in idx_l:
            try:
                cols = list(df.columns)
                if col_idx >= len(cols):
                    return None
                return _safe_float(df.loc[idx_l[key], cols[col_idx]])
            except Exception:
                return None
        for ik, orig in idx_l.items():
            if key in ik or ik in key:
                try:
                    cols = list(df.columns)
                    if col_idx >= len(cols):
                        return None
                    return _safe_float(df.loc[orig, cols[col_idx]])
                except Exception:
                    continue
    return None


def _fetch_finansal_ozet(ticker) -> Dict[str, Any]:
    """Yıllık + son çeyrek ciro/net/FCF/bilanço — yoksa {}."""
    out: Dict[str, Any] = {}
    try:
        fin = getattr(ticker, "financials", None)
        qfin = getattr(ticker, "quarterly_financials", None)
        cf = getattr(ticker, "cashflow", None)
        qcf = getattr(ticker, "quarterly_cashflow", None)
        bs = getattr(ticker, "balance_sheet", None)
        qbs = getattr(ticker, "quarterly_balance_sheet", None)
    except Exception as e:
        _log.debug("temel_veri finans erişim: %s", e)
        return out

    rev_names = ("Total Revenue", "Operating Revenue", "TotalRevenue")
    ni_names = ("Net Income", "Net Income Common Stockholders", "NetIncome")
    fcf_names = ("Free Cash Flow", "FreeCashFlow")
    inv_names = ("Investing Cash Flow", "Cash Flow From Continuing Investing Activities")
    fin_names = ("Financing Cash Flow", "Cash Flow From Continuing Financing Activities")
    asset_names = ("Total Assets", "TotalAssets")
    liab_names = (
        "Total Liabilities Net Minority Interest",
        "Total Liabilities",
        "TotalLiabilitiesNetMinorityInterest",
    )

    out["revenue_y"] = _df_cell(fin, rev_names, 0)
    out["revenue_y_prev"] = _df_cell(fin, rev_names, 1)
    out["net_income_y"] = _df_cell(fin, ni_names, 0)
    out["revenue_q"] = _df_cell(qfin, rev_names, 0)
    out["net_income_q"] = _df_cell(qfin, ni_names, 0)

    out["fcf_y"] = _df_cell(cf, fcf_names, 0)
    out["fcf_q"] = _df_cell(qcf, fcf_names, 0)
    out["investing_y"] = _df_cell(cf, inv_names, 0)
    out["investing_q"] = _df_cell(qcf, inv_names, 0)
    out["financing_y"] = _df_cell(cf, fin_names, 0)
    out["financing_q"] = _df_cell(qcf, fin_names, 0)

    out["total_assets_y"] = _df_cell(bs, asset_names, 0)
    out["total_liab_y"] = _df_cell(bs, liab_names, 0)
    out["total_assets_q"] = _df_cell(qbs, asset_names, 0)
    out["total_liab_q"] = _df_cell(qbs, liab_names, 0)

    # Boşları temizle
    out = {k: v for k, v in out.items() if v is not None}

    rev = out.get("revenue_y")
    ni = out.get("net_income_y")
    if rev and rev != 0 and ni is not None:
        out["profit_margin_y"] = ni / rev

    if out:
        out["finans_guncelleme"] = _bugun()
    return out


def _fetch_one_info(sembol: str) -> Dict[str, Any]:
    """Tek sembol .info + finansal özet — timeout çağıranda; hata → {}."""
    sym = (sembol or "").strip().upper()
    if not sym:
        return {}
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        info = t.info or {}
    except Exception as e:
        _log.warning("temel_veri %s: info hatası: %s", sym, e)
        return {}
    out: Dict[str, Any] = {}
    for k in INFO_ALANLAR:
        v = info.get(k)
        if v is None:
            continue
        if k in (
            "trailingPE", "forwardPE", "earningsGrowth", "revenueGrowth",
            "targetMeanPrice", "numberOfAnalystOpinions",
            "currentPrice", "regularMarketPrice", "profitMargins",
        ):
            fv = _safe_float(v)
            if fv is not None:
                out[k] = fv
        else:
            out[k] = v
    qt = info.get("quoteType")
    if qt:
        out["quoteType"] = qt
    # Analist dağılımı (strongBuy+buy = al_sayi) — get_recommendations_summary
    rec = _fetch_rec_counts(t)
    out.update(rec)
    # ETF/emtia: bilanço çekme (gereksiz / yok)
    qt_u = str(qt or "").upper()
    if qt_u not in ("ETF", "MUTUALFUND", "INDEX", "CURRENCY", "FUTURE"):
        try:
            fin = _fetch_finansal_ozet(t)
            out.update(fin)
        except Exception as e:
            _log.debug("temel_veri %s finans: %s", sym, e)
    out["guncelleme"] = _bugun()
    return out


def _fetch_rec_counts(ticker) -> Dict[str, Any]:
    """
    Yahoo recommendations summary → al_sayi = strongBuy + buy (period 0m).
    Detay yoksa {} — skor label sayı göstermez (yanıltıcı tek toplam yok).
    """
    try:
        df = None
        if hasattr(ticker, "get_recommendations_summary"):
            df = ticker.get_recommendations_summary()
        elif hasattr(ticker, "recommendations_summary"):
            df = ticker.recommendations_summary
        if df is None or getattr(df, "empty", True):
            return {}
        if "period" in df.columns:
            row = df[df["period"].astype(str).str.strip() == "0m"]
            if row.empty:
                row = df.iloc[[0]]
        else:
            row = df.iloc[[0]]
        r = row.iloc[0]

        def _i(*keys: str) -> int:
            for k in keys:
                if k not in r.index:
                    continue
                try:
                    return int(float(r[k]))
                except (TypeError, ValueError):
                    continue
            return 0

        sb = _i("strongBuy", "strong_buy")
        b = _i("buy")
        h = _i("hold")
        s = _i("sell")
        ss = _i("strongSell", "strong_sell")
        al = sb + b
        return {
            "strongBuy": sb,
            "buy": b,
            "hold": h,
            "sell": s,
            "strongSell": ss,
            "al_sayi": al,  # 0 geçerli; skor_label None kontrolü yapar
        }
    except Exception as e:
        _log.debug("temel_veri rec_counts: %s", e)
        return {}


def _rec_counts_eksik(entry: Optional[dict]) -> bool:
    """Hisse cache'de analist var ama al_sayi/strongBuy yok → yeniden çek."""
    if not entry or entry.get("_bos"):
        return False
    if (entry.get("quoteType") or "").upper() == "ETF" or _etf_gibi(entry):
        return False
    if entry.get("al_sayi") is not None:
        return False
    if entry.get("strongBuy") is not None or entry.get("buy") is not None:
        return False
    return bool(
        entry.get("numberOfAnalystOpinions") is not None
        or entry.get("recommendationKey")
    )


def _fetch_rec_counts_sembol(sembol: str) -> Dict[str, Any]:
    sym = (sembol or "").strip().upper()
    if not sym:
        return {}
    try:
        import yfinance as yf

        return _fetch_rec_counts(yf.Ticker(sym))
    except Exception as e:
        _log.debug("temel_veri rec_counts %s: %s", sym, e)
        return {}


def _progress_emit(cb: ProgressCb, done: int, total: int, mesaj: str) -> None:
    if not cb:
        return
    try:
        cb(done, total, mesaj)
    except Exception:
        pass


def ensure_al_sayi(
    semboller: Iterable[str],
    *,
    max_workers: int = MAX_WORKERS,
    timeout: float = 2.5,
    persist: bool = True,
    cache: Optional[Dict[str, dict]] = None,
    progress_cb: ProgressCb = None,
    progress_offset: int = 0,
    progress_total: Optional[int] = None,
) -> Dict[str, dict]:
    """
    Cache'de al_sayi eksik hisseler için yalnızca recommendations_summary çeker.
    Tablo/PDF öncesi çağrılır — 'AL55' yerine 'AL53/55' üretir.
    """
    cache = dict(cache if cache is not None else yukle_cache())
    uniq = list(dict.fromkeys((s or "").strip().upper() for s in semboller if s))
    need = [s for s in uniq if _rec_counts_eksik(cache.get(s))]
    if not need:
        return cache

    def _one(sym: str) -> Tuple[str, Dict[str, Any]]:
        # İç içe ThreadPool yok — FD sızıntısı (Errno 24) önlenir
        old = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(max(1.0, float(timeout)))
            return sym, _fetch_rec_counts_sembol(sym)
        except Exception as e:
            _log.debug("ensure_al_sayi %s: %s", sym, e)
            return sym, {}
        finally:
            try:
                socket.setdefaulttimeout(old)
            except Exception:
                pass

    workers = max(1, min(max_workers, len(need)))
    dirty = False
    total = progress_total if progress_total is not None else (progress_offset + len(need))
    done_local = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(_one, s) for s in need]):
            try:
                sym, rec = fut.result()
            except Exception:
                sym, rec = "?", {}
            done_local += 1
            if rec and rec.get("al_sayi") is not None:
                ent = dict(cache.get(sym) or {})
                ent.update(rec)
                if not ent.get("guncelleme"):
                    ent["guncelleme"] = _bugun()
                cache[sym] = ent
                dirty = True
            _progress_emit(
                progress_cb,
                progress_offset + done_local,
                total,
                f"Analist sayısı: {sym}",
            )
    if dirty and persist:
        kaydet_cache(cache)
    return cache


def _fetch_one_with_timeout(sembol: str, timeout: float = SYMBOL_TIMEOUT_SEC) -> Dict[str, Any]:
    """Tek sembol çekimi — iç içe executor yok (FD tükenmesin)."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(max(1.0, float(timeout)))
        return _fetch_one_info(sembol)
    except Exception as e:
        _log.warning("temel_veri %s: timeout/hata (%.1fs): %s", sembol, timeout, e)
        return {}
    finally:
        try:
            socket.setdefaulttimeout(old)
        except Exception:
            pass


def temel_veri_cek(
    semboller: Iterable[str],
    *,
    force: bool = False,
    max_workers: int = MAX_WORKERS,
    timeout: float = SYMBOL_TIMEOUT_SEC,
    cache: Optional[Dict[str, dict]] = None,
    persist: bool = True,
    progress_cb: ProgressCb = None,
) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """
    Paralel .info çekimi + 24s TTL cache.
    Dönüş: (sembol→alanlar, istatistik: ok/fail/etf/cache_hit)
    """
    cache = dict(cache if cache is not None else yukle_cache())
    uniq = list(dict.fromkeys((s or "").strip().upper() for s in semboller if s))
    stats = {"ok": 0, "fail": 0, "etf": 0, "cache_hit": 0, "fetched": 0}
    need: List[str] = []
    rec_patch: List[str] = []
    def _finans_eksik(ent: dict) -> bool:
        if (ent.get("quoteType") or "").upper() == "ETF" or _etf_gibi(ent):
            return False
        return (
            ent.get("finans_guncelleme") is None
            and ent.get("revenue_y") is None
            and ent.get("fcf_y") is None
        )

    for sym in uniq:
        ent = cache.get(sym)
        # _bos = önceki boş çekim — tarama doldurmada yeniden dene
        if not force and ent and _cache_taze(ent) and not ent.get("_bos"):
            if _finans_eksik(ent):
                need.append(sym)
                continue
            if _rec_counts_eksik(ent):
                rec_patch.append(sym)
            stats["cache_hit"] += 1
            if (ent.get("quoteType") or "").upper() == "ETF" or _etf_gibi(ent):
                stats["etf"] += 1
            elif ent.get("trailingPE") is not None or ent.get("recommendationKey"):
                stats["ok"] += 1
            else:
                stats["fail"] += 1
            continue
        need.append(sym)

    job_total = len(need) + len(rec_patch)
    # rec_patch, need içinde de olabilir — çift sayma olmasın
    rec_only = [s for s in rec_patch if s not in set(need)]
    job_total = len(need) + len(rec_only)
    stats["job_total"] = job_total

    t0 = time.time()
    done = 0
    if job_total:
        _cleanup_cache_tmps()
        _progress_emit(progress_cb, 0, job_total, "Başlıyor…")
    if need:
        workers = max(1, min(max_workers, len(need)))
        done_since_save = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_fetch_one_with_timeout, s, timeout): s for s in need}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    data = fut.result()
                except Exception as e:
                    _log.warning("temel_veri %s: worker: %s", sym, e)
                    data = {}
                if not data:
                    cache[sym] = {"guncelleme": _bugun(), "_bos": True}
                    stats["fail"] += 1
                    stats["fetched"] += 1
                    durum = "boş/hata"
                else:
                    cache[sym] = data
                    stats["fetched"] += 1
                    if (data.get("quoteType") or "").upper() == "ETF" or _etf_gibi(data):
                        stats["etf"] += 1
                        durum = "ETF"
                    elif data.get("trailingPE") is not None or data.get("recommendationKey"):
                        stats["ok"] += 1
                        durum = "OK"
                    else:
                        stats["fail"] += 1
                        durum = "kısmi"
                done += 1
                done_since_save += 1
                _progress_emit(
                    progress_cb, done, job_total,
                    f"Temel veri: {sym} ({durum})",
                )
                # Uzun çekimde yarıda kesilirse ilerleme kaybolmasın
                if persist and done_since_save >= 10:
                    kaydet_cache(cache)
                    done_since_save = 0
        if persist:
            kaydet_cache(cache)
    if rec_only:
        cache = ensure_al_sayi(
            rec_only,
            max_workers=max_workers,
            timeout=min(2.5, timeout),
            persist=persist,
            cache=cache,
            progress_cb=progress_cb,
            progress_offset=done,
            progress_total=job_total,
        )
        stats["rec_patched"] = sum(
            1 for s in rec_only
            if (cache.get(s) or {}).get("al_sayi") is not None
        )
    elapsed = time.time() - t0
    stats["elapsed_sec"] = round(elapsed, 2)
    stats["avg_sec"] = round(elapsed / max(1, len(need)), 3) if need else 0.0
    stats["cache_bytes"] = os.path.getsize(STATE_PATH) if os.path.isfile(STATE_PATH) else 0
    return cache, stats


def get_temel(sembol: str, *, force: bool = False) -> Dict[str, Any]:
    """Tek sembol — cache veya çekim."""
    cache, _ = temel_veri_cek([sembol], force=force)
    return dict(cache.get((sembol or "").strip().upper(), {}))


def temel_veri_tarama_icin(
    semboller: Iterable[str],
    *,
    force: bool = False,
    max_workers: int = MAX_WORKERS,
    progress_cb: ProgressCb = None,
) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """
    Hisse tarama tablosu öncesi: eksik .info + al_sayi cache'ini doldur.
    ETF sembolleri çağıran tarafça elenebilir; ETF gelirse zararsız (konsensüs yok).
    """
    cache, stats = temel_veri_cek(
        semboller,
        force=force,
        max_workers=max_workers,
        persist=True,
        progress_cb=progress_cb,
    )
    # Çekim sonrası hâlâ al_sayi eksik kalanları bir tur daha dene
    eksik = [
        s for s in ((x or "").strip().upper() for x in semboller if x)
        if _rec_counts_eksik(cache.get(s))
    ]
    if eksik:
        base = int(stats.get("job_total") or 0)
        total = base + len(eksik)
        cache = ensure_al_sayi(
            eksik,
            max_workers=max_workers,
            persist=True,
            cache=cache,
            progress_cb=progress_cb,
            progress_offset=base,
            progress_total=total,
        )
        stats["rec_patched"] = stats.get("rec_patched", 0) + sum(
            1 for s in eksik if (cache.get(s) or {}).get("al_sayi") is not None
        )
        stats["job_total"] = total
    analistli = sum(
        1 for s in ((x or "").strip().upper() for x in semboller if x)
        if (cache.get(s) or {}).get("recommendationKey")
        and not (cache.get(s) or {}).get("_bos")
    )
    stats["analistli"] = analistli
    stats["istenen"] = len(list(dict.fromkeys(
        (x or "").strip().upper() for x in semboller if x
    )))
    if progress_cb and stats.get("job_total"):
        _progress_emit(
            progress_cb,
            int(stats["job_total"]),
            int(stats["job_total"]),
            "Tamamlandı",
        )
    return cache, stats


def _etf_gibi(temel: dict) -> bool:
    return str((temel or {}).get("quoteType") or "").upper() == "ETF"


def _kaynak_pb(currency: Optional[str]) -> str:
    c = (currency or "").upper()
    if c in ("GBp", "GBX"):
        return "GBP"
    if c == "TRY":
        return "TL"
    if c in ("USD", "EUR", "GBP", "TL", "CHF"):
        return c
    return "USD"


def _buyume_metin(temel: dict) -> Optional[str]:
    eg = _safe_float(temel.get("earningsGrowth"))
    if eg is not None:
        return f"{eg * 100:+.0f}% kazanç"
    rg = _safe_float(temel.get("revenueGrowth"))
    if rg is not None:
        return f"{rg * 100:+.0f}% gelir"
    return None


def temel_veri_notu(
    sembol: str,
    temel: Optional[dict],
    fiyat_eur: Optional[float],
    *,
    tur: str = "hisse",
    eur_try: float = 0.0,
    usd_try: float = 0.0,
    gbp_usd: Optional[float] = None,
    eur_usd: Optional[float] = None,
    chf_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """UI / Neden? paneli için değerleme notu dict."""
    tur_l = (tur or "hisse").lower()
    if tur_l == "etf" or (temel and (temel.get("quoteType") or "").upper() == "ETF"):
        return {
            "tur": "etf",
            "not": "ETF için analist konsensüsü yok",
            "fk_trailing": None,
            "fk_forward": None,
            "analist": None,
            "analist_sayi": None,
            "al_sayi": None,
            "hedef_eur": None,
            "hedef_fark_pct": None,
            "buyume": None,
            "kaynak": "Yahoo Finance",
            "guncelleme": (temel or {}).get("guncelleme") or _bugun(),
            "sembol": sembol,
        }

    temel = temel or {}
    fk_t = _safe_float(temel.get("trailingPE"))
    fk_f = _safe_float(temel.get("forwardPE"))
    analist = temel.get("recommendationKey")
    if analist is not None:
        analist = str(analist).lower()
    n_op = _safe_float(temel.get("numberOfAnalystOpinions"))
    n_op_i = int(n_op) if n_op is not None else None

    al_sayi = temel.get("al_sayi")
    if al_sayi is None:
        sb = _safe_float(temel.get("strongBuy"))
        b = _safe_float(temel.get("buy"))
        if sb is not None or b is not None:
            al_sayi = int((sb or 0) + (b or 0))
    if al_sayi is not None:
        try:
            al_sayi = int(al_sayi)
        except (TypeError, ValueError):
            al_sayi = None

    hedef_eur = None
    hedef_fark = None
    target = _safe_float(temel.get("targetMeanPrice"))
    if target is not None and eur_try > 0 and usd_try > 0:
        from fiyat_para import pb_cevir

        src = _kaynak_pb(temel.get("currency"))
        # GBp listing: target genelde major unit (GBP) — Yahoo BIST/US major
        try:
            hedef_eur = pb_cevir(
                target, src, "EUR", eur_try, usd_try,
                gbp_usd=gbp_usd, eur_usd=eur_usd, chf_usd=chf_usd,
            )
        except Exception as e:
            _log.warning("temel_veri %s hedef EUR: %s", sembol, e)
            hedef_eur = None
        if hedef_eur is not None and fiyat_eur and fiyat_eur > 0:
            hedef_fark = (hedef_eur / float(fiyat_eur) - 1.0) * 100.0

    # FX yoksa aynı para biriminde hedef/spot
    if hedef_fark is None and target is not None:
        spot = _safe_float(temel.get("currentPrice")) or _safe_float(
            temel.get("regularMarketPrice")
        )
        if spot and spot > 0:
            hedef_fark = (target / spot - 1.0) * 100.0

    buyume = _buyume_metin(temel)
    return {
        "tur": "hisse",
        "fk_trailing": round(fk_t, 2) if fk_t is not None else None,
        "fk_forward": round(fk_f, 2) if fk_f is not None else None,
        "analist": analist,
        "analist_sayi": n_op_i,
        "al_sayi": al_sayi,
        "hedef_eur": round(hedef_eur, 2) if hedef_eur is not None else None,
        "hedef_fark_pct": round(hedef_fark, 1) if hedef_fark is not None else None,
        "buyume": buyume,
        "kaynak": "Yahoo Finance",
        "guncelleme": temel.get("guncelleme") or _bugun(),
        "sembol": sembol,
        "not": None,
    }


# Kompozit sinyal (skor + analist + hedef) — UI emoji / PDF geometrik
SINYAL_YUKARI = "🔼"
SINYAL_NOTR = "⏸"
SINYAL_ASAGI = "🔽"
# Arial Unicode: ❚ kare gibi görünür → ↑ = ↓ (net, glyph var)
_SINYAL_PDF = {
    SINYAL_YUKARI: "↑",
    SINYAL_NOTR: "=",
    SINYAL_ASAGI: "↓",
}
_SINYAL_TOOLTIP_ANALIST = {
    SINYAL_YUKARI: "Momentum ▲ — skor/analist sıcak; bu «Şimdi ne yap?» değildir",
    SINYAL_NOTR: "Momentum nötr — skor/analist karışık; aksiyon sütununa bakın",
    SINYAL_ASAGI: "Momentum ▼ — skor/analist zayıf; aksiyon sütununa bakın",
}
_SINYAL_TOOLTIP_MOTOR = {
    SINYAL_YUKARI: "Güçlü momentum rozeti (analist yok) — «Şimdi ne yap?» değildir",
    SINYAL_NOTR: "Nötr momentum rozeti (analist yok)",
    SINYAL_ASAGI: "Zayıf momentum rozeti (analist yok)",
}
_ANALIST_BUY = frozenset({"buy", "strong_buy"})
_ANALIST_HOLD_SELL = frozenset({"hold", "neutral", "sell", "strong_sell"})


def _analist_mevcut(temel: Optional[dict]) -> bool:
    """ETF/emtia veya recommendationKey yok → motor-only kural."""
    if not temel or temel.get("tur") in ("etf", "emtia"):
        return False
    a = str(temel.get("analist") or "").lower()
    return a in _ANALIST_BUY or a in _ANALIST_HOLD_SELL


def sinyal_isaret(skor, temel: Optional[dict] = None) -> str:
    """
    1) Motor + analist:
       🔼 skor≥60 ∧ buy ∧ hedef>+15%
       🔽 skor<42 ∧ hold/sell ∧ hedef≤+10%
    2) Sadece motor (ETF / emtia / analist yok):
       🔼 skor≥66 · 🔽 skor<42 · ⏸ aksi
    """
    try:
        s = float(skor)
    except (TypeError, ValueError):
        return SINYAL_NOTR

    if not _analist_mevcut(temel):
        if s >= 66:
            return SINYAL_YUKARI
        if s < 42:
            return SINYAL_ASAGI
        return SINYAL_NOTR

    assert temel is not None
    analist = str(temel.get("analist") or "").lower()
    fark = temel.get("hedef_fark_pct")
    try:
        fark_f = float(fark) if fark is not None else None
    except (TypeError, ValueError):
        fark_f = None

    # Kural metni ≥60; BIMAS örneği skor 59 + 💚+37% → 🔼 (bir puan tolerans)
    if s >= 59 and analist in _ANALIST_BUY and fark_f is not None and fark_f > 15:
        return SINYAL_YUKARI
    # NFLX örn. 🟡+10% → 🔽 (sınır dahil)
    if s < 42 and analist in _ANALIST_HOLD_SELL and fark_f is not None and fark_f <= 10:
        return SINYAL_ASAGI
    return SINYAL_NOTR


def sinyal_tooltip(isaret: str, *, analist_var: bool = True) -> str:
    m = _SINYAL_TOOLTIP_ANALIST if analist_var else _SINYAL_TOOLTIP_MOTOR
    return m.get(isaret, m[SINYAL_NOTR])


def sinyal_pdf_safe(isaret: str) -> str:
    return _SINYAL_PDF.get(isaret, isaret)


def _varlik_tur_label(h) -> str:
    if getattr(h, "piyasa", "") == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia":
        return "emtia"
    if getattr(h, "piyasa", "") == "ETF" or getattr(h, "varlik_turu", "") == "etf":
        return "etf"
    return "hisse"


def sinyal_isaret_hisse(h, *, fx=None) -> str:
    """Hisse/ETF/emtia nesnesinden 🔼/⏸/🔽 (temel cache; analist yoksa motor)."""
    if getattr(h, "signal_v2_score", None) is not None:
        skor = h.signal_v2_score
    else:
        skor = getattr(h, "skor", None)

    tur = _varlik_tur_label(h)
    if tur in ("etf", "emtia"):
        return sinyal_isaret(skor, {"tur": tur})

    cache = yukle_cache()
    sym = (getattr(h, "sembol", "") or "").strip().upper()
    raw = cache.get(sym) or {}
    if not raw or raw.get("_bos"):
        kok = sym.split(".")[0]
        for k, v in cache.items():
            if str(k).split(".")[0] == kok and isinstance(v, dict) and not v.get("_bos"):
                raw = v
                break
    # UI satırında Yahoo çağırma — eksik al_sayi motor-only / kısmi etiket
    if not raw or raw.get("_bos"):
        # Cache yok — motor-only
        return sinyal_isaret(skor, None)

    fiyat_eur = None
    if fx is not None and getattr(h, "fiyat", None):
        try:
            from fiyat_para import tablo_fiyat

            fiyat_eur = tablo_fiyat(
                h.fiyat, "EUR", fx.eur_try, fx.usd_try,
                sembol=h.sembol,
                piyasa=getattr(h, "piyasa", ""),
                varlik_turu=getattr(h, "varlik_turu", ""),
                quote_currency=getattr(h, "quote_currency", "") or "",
                gbp_usd=getattr(fx, "gbp_usd", None),
                eur_usd=getattr(fx, "eur_usd", None),
                chf_usd=getattr(fx, "chf_usd", None),
            )
        except Exception:
            fiyat_eur = None

    notu = temel_veri_notu(
        h.sembol, raw, fiyat_eur, tur=tur,
        eur_try=(getattr(fx, "eur_try", 0) or 0) if fx else 0,
        usd_try=(getattr(fx, "usd_try", 0) or 0) if fx else 0,
        gbp_usd=getattr(fx, "gbp_usd", None) if fx else None,
        eur_usd=getattr(fx, "eur_usd", None) if fx else None,
        chf_usd=getattr(fx, "chf_usd", None) if fx else None,
    )
    return sinyal_isaret(skor, notu)


# PDF font (Arial Unicode) emoji glyph taşımıyor → ASCII yön etiketi
_SKOR_YON_UI = {
    "strong_buy": "💚",
    "buy": "💚",
    "hold": "🟡",
    "neutral": "🟡",
    "sell": "🔴",
    "strong_sell": "🔴",
}
_SKOR_YON_PDF = {
    "strong_buy": "AL",
    "buy": "AL",
    "hold": "TUT",
    "neutral": "TUT",
    "sell": "SAT",
    "strong_sell": "SAT",
}


def skor_label_pdf_safe(label: str) -> str:
    """UI skor etiketindeki emojiyi PDF-uyumlu AL/TUT/SAT ile değiştir."""
    if not label:
        return label
    s = str(label)
    for emo, txt in (("💚", "AL"), ("🟡", "TUT"), ("🔴", "SAT")):
        s = s.replace(emo, txt)
    return s


def skor_label(
    skor,
    percentile,
    temel: Optional[dict] = None,
    *,
    pdf_safe: bool = False,
) -> str:
    """
    Tablo Skor hücresi: "65 (99%) 💚14/14 +37%"
    pdf_safe=True → "65 (99%) AL14/14 +37%" (Arial Unicode emoji yok)
    ETF / veri yok → yalnızca skor (percentile).
    """
    try:
        s = float(skor)
        base = f"{s:.0f}"
    except (TypeError, ValueError):
        base = str(skor)
    if percentile is not None:
        try:
            base = f"{base} ({float(percentile):.0f}%)"
        except (TypeError, ValueError):
            pass

    if not temel or temel.get("tur") in ("etf", "emtia"):
        return base

    yon_map = _SKOR_YON_PDF if pdf_safe else _SKOR_YON_UI
    yon = yon_map.get(str(temel.get("analist") or "").lower(), "")
    if not yon:
        return base

    toplam = temel.get("analist_sayi")
    al_sayi = temel.get("al_sayi")
    # Sadece X/Y — tek başına toplam (AL55) yanıltıcı, gösterme
    if al_sayi is not None and toplam:
        sayi_str = f"{int(al_sayi)}/{int(toplam)}"
    elif al_sayi is not None:
        sayi_str = f"{int(al_sayi)}"
    else:
        sayi_str = ""

    fark = temel.get("hedef_fark_pct")
    fark_str = f"{float(fark):+.0f}%" if fark is not None else ""

    parts = [base, yon + sayi_str, fark_str]
    return " ".join(p for p in parts if p).strip()


def skor_etiket_hisse(h, *, fx=None, pdf_safe: bool = False) -> Any:
    """
    Hisse/ETF nesnesinden skor etiketi (UI veya PDF).
    v2 yoksa ham skor (float); v2 varsa skor_label metni.
    """
    if getattr(h, "signal_v2_score", None) is not None:
        p = getattr(h, "signal_v2_percentile", None)
        s = h.signal_v2_score
    else:
        return round(getattr(h, "skor", 0) or 0, 0)

    tur = _varlik_tur_label(h)
    if tur in ("etf", "emtia"):
        return skor_label(s, p, {"tur": tur}, pdf_safe=pdf_safe)

    cache = yukle_cache()
    sym = (getattr(h, "sembol", "") or "").strip().upper()
    raw = cache.get(sym) or {}
    if not raw or raw.get("_bos"):
        kok = sym.split(".")[0]
        for k, v in cache.items():
            if str(k).split(".")[0] == kok and isinstance(v, dict) and not v.get("_bos"):
                raw = v
                break
    # UI satırında Yahoo çağırma — cache yoksa yalnızca skor (percentile)
    if not raw or raw.get("_bos"):
        return skor_label(s, p, None, pdf_safe=pdf_safe)

    fiyat_eur = None
    if fx is not None and getattr(h, "fiyat", None):
        try:
            from fiyat_para import tablo_fiyat

            fiyat_eur = tablo_fiyat(
                h.fiyat, "EUR", fx.eur_try, fx.usd_try,
                sembol=h.sembol,
                piyasa=getattr(h, "piyasa", ""),
                varlik_turu=getattr(h, "varlik_turu", ""),
                quote_currency=getattr(h, "quote_currency", "") or "",
                gbp_usd=getattr(fx, "gbp_usd", None),
                eur_usd=getattr(fx, "eur_usd", None),
                chf_usd=getattr(fx, "chf_usd", None),
            )
        except Exception:
            fiyat_eur = None

    notu = temel_veri_notu(
        h.sembol, raw, fiyat_eur, tur=tur,
        eur_try=(getattr(fx, "eur_try", 0) or 0) if fx else 0,
        usd_try=(getattr(fx, "usd_try", 0) or 0) if fx else 0,
        gbp_usd=getattr(fx, "gbp_usd", None) if fx else None,
        eur_usd=getattr(fx, "eur_usd", None) if fx else None,
        chf_usd=getattr(fx, "chf_usd", None) if fx else None,
    )
    return skor_label(s, p, notu, pdf_safe=pdf_safe)


def format_degerleme_markdown(notu: Dict[str, Any]) -> str:
    """Neden? paneli — Değerleme bölümü."""
    if not notu:
        return ""
    if notu.get("tur") == "etf" or notu.get("not"):
        gun = _format_gun_tr(notu.get("guncelleme"))
        return (
            "### Değerleme\n\n"
            f"{notu.get('not') or 'ETF için analist konsensüsü yok'}\n\n"
            f"[Yahoo Finance · {gun}]"
        )

    lines = ["### Değerleme", ""]
    fk_t, fk_f = notu.get("fk_trailing"), notu.get("fk_forward")
    if fk_t is not None or fk_f is not None:
        if fk_t is not None and fk_f is not None:
            lines.append(f"F/K: {fk_t:.1f}x (ileri: {fk_f:.1f}x)")
        elif fk_t is not None:
            lines.append(f"F/K: {fk_t:.1f}x")
        else:
            lines.append(f"F/K ileri: {fk_f:.1f}x")

    analist = notu.get("analist")
    n = notu.get("analist_sayi")
    hedef = notu.get("hedef_eur")
    fark = notu.get("hedef_fark_pct")
    if analist:
        etiket = _ANALIST_TR.get(analist, analist)
        if n:
            parca = f"Analist: {n}/{n} → {etiket}"
        else:
            parca = f"Analist: {etiket}"
        if hedef is not None:
            fark_s = f" ({fark:+.1f}%)" if fark is not None else ""
            parca += f" | Hedef: {hedef:.2f} EUR{fark_s}"
        lines.append(parca)
    elif hedef is not None:
        fark_s = f" ({fark:+.1f}%)" if fark is not None else ""
        lines.append(f"Hedef: {hedef:.2f} EUR{fark_s}")
    else:
        lines.append("Analist: veri yok")

    if notu.get("buyume"):
        lines.append(f"Büyüme: {notu['buyume']}")

    gun = _format_gun_tr(notu.get("guncelleme"))
    lines.extend(["", f"[Yahoo Finance · {gun}]"])
    return "\n".join(lines)


def _format_gun_tr(iso: Optional[str]) -> str:
    d = _parse_gun(iso or "")
    if d is None:
        return iso or "—"
    aylar = (
        "Oca", "Şub", "Mar", "Nis", "May", "Haz",
        "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
    )
    return f"{d.day} {aylar[d.month - 1]} {d.year}"


def rapor_ozet(stats: Dict[str, Any], ornekler: Optional[Dict[str, dict]] = None) -> str:
    lines = [
        "## Temel veri çekim raporu",
        f"- Başarılı (F/K veya analist): {stats.get('ok', 0)}",
        f"- Başarısız / boş: {stats.get('fail', 0)}",
        f"- ETF (veri yok): {stats.get('etf', 0)}",
        f"- Cache hit: {stats.get('cache_hit', 0)}",
        f"- Çekilen: {stats.get('fetched', 0)}",
        f"- Süre (paralel): {stats.get('elapsed_sec', 0)} s "
        f"(ort. {stats.get('avg_sec', 0)} s/sembol)",
        f"- Cache boyutu: {stats.get('cache_bytes', 0)} byte",
    ]
    if ornekler:
        lines.append("- Örnek notlar:")
        for k, v in ornekler.items():
            lines.append(f"  - {k}: {v}")
    return "\n".join(lines)
