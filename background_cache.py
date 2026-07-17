# -*- coding: utf-8 -*-
"""Sessiz arka plan: canlı fiyat (≤15 dk) + bayat tarama + analist cache."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence

_log = logging.getLogger(__name__)

LogFn = Callable[[str], None]


def _default_log(msg: str) -> None:
    _log.info(msg)
    print(msg, flush=True)


def universe_quote_symbols() -> List[str]:
    from stock_scanner import ENDEKSLER
    from stock_universe import tum_evren

    syms = list(ENDEKSLER.values()) + [s for s, *_ in tum_evren()]
    syms += ["EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X"]
    return list(dict.fromkeys(s for s in syms if s))


def universe_analist_symbols() -> List[str]:
    """Hisse evreni — ETF/emtia hariç (analist konsensüsü yok)."""
    from stock_universe import tum_evren

    out: List[str] = []
    for sembol, _ad, piyasa, *_rest in tum_evren():
        if piyasa in ("ETF", "EMTIA"):
            continue
        if sembol:
            out.append(sembol.strip().upper())
    return list(dict.fromkeys(out))


def analist_eksik_semboller(
    semboller: Iterable[str],
    *,
    cache: Optional[dict] = None,
) -> List[str]:
    """TTL dolmuş, boş, _bos veya recommendationKey yok / al_sayi eksik."""
    from temel_veri import _cache_taze, _rec_counts_eksik, yukle_cache

    c = cache if cache is not None else yukle_cache()
    need: List[str] = []
    for raw in semboller:
        s = (raw or "").strip().upper()
        if not s:
            continue
        ent = c.get(s)
        if not ent or not _cache_taze(ent) or ent.get("_bos"):
            need.append(s)
            continue
        # Taze ama analist etiketi yok → yeniden çek (eski kısmi kayıt)
        if not ent.get("recommendationKey"):
            need.append(s)
            continue
        if _rec_counts_eksik(ent):
            need.append(s)
    return list(dict.fromkeys(need))


def analist_hazir_say(semboller: Sequence[str]) -> tuple:
    """(hazır, toplam) — recommendationKey + taze. Diskten taze oku."""
    from temel_veri import _cache_taze, yukle_cache
    import temel_veri as tv

    # Arka plan yazımı sonrası bayat bellek olmasın
    tv._yukle_mtime = None
    c = yukle_cache()
    uniq = list(dict.fromkeys((s or "").strip().upper() for s in semboller if s))
    ok = sum(
        1
        for s in uniq
        if c.get(s)
        and _cache_taze(c[s])
        and not c[s].get("_bos")
        and c[s].get("recommendationKey")
    )
    return ok, len(uniq)


def refresh_live_quotes_quiet(
    symbols: Optional[Iterable[str]] = None,
    *,
    max_workers: int = 3,
    log: LogFn = _default_log,
) -> Dict[str, object]:
    from signal_engine.data.live_quote import live_quotes_cache_age_sec, refresh_live_quotes

    syms = list(symbols) if symbols is not None else universe_quote_symbols()
    t0 = time.time()
    refresh_live_quotes(
        syms, force=True, max_workers=max_workers, min_refresh_sec=0, persist=True,
    )
    age = live_quotes_cache_age_sec()
    elapsed = time.time() - t0
    log(f"[cache] live quotes: {len(syms)} sembol · {elapsed:.1f}s · yaş={age}")
    return {"symbols": len(syms), "elapsed_sec": elapsed, "age_sec": age}


def refresh_stale_tarama(
    *,
    log: LogFn = _default_log,
    force: bool = False,
) -> Dict[str, object]:
    """Varsayılan profil/rejim tarama anahtarı — yalnızca TTL dolunca tam_tarama."""
    import config
    from allocation_engine import tahsis_hesapla
    from disk_onbellek import TTL, disk_getir, disk_yaz
    from investor_profile import YatirimProfili
    from macro_data import canli_snapshot
    from stock_scanner import tam_tarama

    snap = canli_snapshot()
    profil = YatirimProfili(risk=config.INVESTOR_RISK, vade=config.INVESTOR_VADE)
    tahsis = tahsis_hesapla(snap, profil)
    rejim = tahsis.rejim.rejim
    anahtar = (
        f"tarama:True:{rejim}:False:{profil.risk}:{profil.vade}:"
        f"v2={int(getattr(config, 'USE_SIGNAL_ENGINE_V2', True))}:gbx_v3:live_v1"
    )
    veri, yas = disk_getir(anahtar, TTL["tarama"], bayat_kabul=True)
    if not force and veri is not None and yas is not None and yas <= TTL["tarama"]:
        log(f"[cache] tarama taze ({yas:.0f}s ≤ {TTL['tarama']}) — atlandı")
        return {"status": "skip", "age_sec": yas, "key": anahtar}

    t0 = time.time()
    log(f"[cache] tarama yenileniyor ({anahtar})…")
    sonuc = tam_tarama(
        makro_rejim=rejim,
        demo=False,
        snap=snap,
        haber_tara=False,
        profil=profil,
        use_signal_v2=getattr(config, "USE_SIGNAL_ENGINE_V2", True),
    )
    if sonuc is not None:
        disk_yaz(anahtar, sonuc)
    elapsed = time.time() - t0
    n = len(getattr(sonuc, "hisseler", None) or [])
    log(f"[cache] tarama OK · {n} hisse · {elapsed:.1f}s")
    return {"status": "ok", "elapsed_sec": elapsed, "n_hisse": n, "key": anahtar}


# Streamlit: uzun Yahoo çekimi rerun ile ölmesin → küçük dalgalar
ANALIST_BATCH_SIZE = 12
_analist_lock = threading.Lock()
_analist_running = False
_quotes_lock = threading.Lock()
_quotes_running = False


def refresh_analist_misses(
    symbols: Optional[Iterable[str]] = None,
    *,
    max_workers: int = 3,
    batch_limit: Optional[int] = None,
    log: LogFn = _default_log,
) -> Dict[str, object]:
    from temel_veri import MAX_WORKERS, temel_veri_tarama_icin

    syms = list(symbols) if symbols is not None else universe_analist_symbols()
    need = analist_eksik_semboller(syms)
    remaining = len(need)
    if batch_limit is not None and batch_limit > 0:
        need = need[: int(batch_limit)]
    if not need:
        ok, tot = analist_hazir_say(syms)
        log(f"[cache] analist taze · {ok}/{tot}")
        return {"status": "skip", "need": 0, "remaining": 0, "ok": ok, "total": tot}

    workers = max(1, min(max_workers, MAX_WORKERS, len(need)))
    t0 = time.time()
    log(f"[cache] analist dalga · {len(need)}/{remaining} eksik (toplam liste {len(syms)})…")
    _cache, stats = temel_veri_tarama_icin(
        need, force=False, max_workers=workers, progress_cb=None,
    )
    elapsed = time.time() - t0
    ok, tot = analist_hazir_say(syms)
    left = len(analist_eksik_semboller(syms))
    log(
        f"[cache] analist dalga OK · hazır {ok}/{tot} · kalan {left} · "
        f"fetched={stats.get('fetched', 0)} · {elapsed:.1f}s"
    )
    return {
        "status": "ok",
        "need": len(need),
        "remaining": left,
        "ok": ok,
        "total": tot,
        "fetched": stats.get("fetched", 0),
        "elapsed_sec": elapsed,
    }


def ensure_analist_batch_daemon(
    symbols: Sequence[str],
    *,
    batch_size: int = ANALIST_BATCH_SIZE,
) -> bool:
    """Tek dalga (≤batch_size) — Streamlit fragment her ~8 sn yeniden tetikler."""
    global _analist_running
    syms = list(dict.fromkeys((s or "").strip().upper() for s in symbols if s))
    if not syms:
        return False
    if not analist_eksik_semboller(syms):
        return False
    with _analist_lock:
        if _analist_running:
            return False
        _analist_running = True

    def _run():
        global _analist_running
        try:
            refresh_analist_misses(
                syms,
                max_workers=3,
                batch_limit=batch_size,
                log=lambda m: _log.info(m),
            )
        except Exception:
            _log.exception("analist batch")
        finally:
            with _analist_lock:
                _analist_running = False

    threading.Thread(target=_run, daemon=True, name="analist-batch").start()
    return True


def ensure_quotes_daemon() -> bool:
    """Fiyat disk önbelleği — analistten bağımsız."""
    global _quotes_running
    from signal_engine.data.live_quote import DISK_TTL_SEC, live_quotes_cache_age_sec

    age = live_quotes_cache_age_sec()
    if age is not None and age <= DISK_TTL_SEC:
        return False
    with _quotes_lock:
        if _quotes_running:
            return False
        _quotes_running = True

    def _run():
        global _quotes_running
        try:
            refresh_live_quotes_quiet(max_workers=3, log=lambda m: _log.info(m))
        except Exception:
            _log.exception("quotes daemon")
        finally:
            with _quotes_lock:
                _quotes_running = False

    threading.Thread(target=_run, daemon=True, name="quotes-refresh").start()
    return True


def run_background_refresh(
    *,
    quotes: bool = True,
    tarama: bool = True,
    analist: bool = True,
    force_tarama: bool = False,
    max_workers: int = 3,
    log: LogFn = _default_log,
) -> Dict[str, object]:
    """LaunchAgent / CLI — tam tur (analistte batch limiti yok)."""
    out: Dict[str, object] = {"ok": True}
    t0 = time.time()
    try:
        if analist:
            out["analist"] = refresh_analist_misses(
                max_workers=max_workers, batch_limit=None, log=log,
            )
        if quotes:
            out["quotes"] = refresh_live_quotes_quiet(max_workers=max_workers, log=log)
        if tarama:
            out["tarama"] = refresh_stale_tarama(log=log, force=force_tarama)
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
        log(f"[cache] HATA: {e}")
        _log.exception("background_cache_refresh")
    out["elapsed_sec"] = time.time() - t0
    return out


def status_caption_parts(
    analist_syms: Optional[Sequence[str]] = None,
) -> str:
    """UI caption: Analist N/M · Fiyat Xm önce."""
    from signal_engine.data.live_quote import live_quotes_cache_age_sec

    parts: List[str] = []
    syms = list(analist_syms) if analist_syms is not None else universe_analist_symbols()
    try:
        ok, tot = analist_hazir_say(syms)
        left = len(analist_eksik_semboller(syms))
        if left:
            parts.append(f"Analist: {ok}/{tot} (kalan {left})")
        else:
            parts.append(f"Analist: {ok}/{tot}")
    except Exception:
        parts.append("Analist: —")
    age = live_quotes_cache_age_sec()
    if age is None:
        parts.append("Fiyat önbelleği: yok")
    else:
        parts.append(f"Fiyat önbelleği: {age / 60.0:.0f} dk önce")
    return " · ".join(parts)


def ensure_silent_refresh_daemon(
    *,
    quotes: bool = True,
    analist: bool = True,
    tarama: bool = False,
    analist_symbols: Optional[Sequence[str]] = None,
    analist_first: bool = True,
) -> bool:
    """Streamlit — analist dalgaları + ayrı fiyat daemon."""
    started = False
    syms = (
        list(analist_symbols)
        if analist_symbols is not None
        else (universe_analist_symbols() if analist else [])
    )
    if analist and syms:
        if ensure_analist_batch_daemon(syms):
            started = True
    if quotes:
        if ensure_quotes_daemon():
            started = True
    if tarama:
        # CLI/LaunchAgent dışı: tarama SWR zaten app_veri'de
        pass
    return started


def analist_hisse_sembolleri(hisseler) -> List[str]:
    """Tarama hisselerinden ETF/emtia hariç semboller."""
    out: List[str] = []
    for h in hisseler or []:
        if getattr(h, "piyasa", "") in ("ETF", "EMTIA"):
            continue
        if getattr(h, "varlik_turu", "") in ("etf", "emtia"):
            continue
        s = (getattr(h, "sembol", "") or "").strip().upper()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))
