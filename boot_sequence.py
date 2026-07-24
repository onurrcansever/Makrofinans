# -*- coding: utf-8 -*-
"""Oturum açılışı — adım adım (her Streamlit rerun’da bir dilim).

Soft açılış: diskte son kayıt varsa UI hemen açılır; boot arka planda
ilerler (quotes/analist bloklamaz). Force / soğuk disk: tam tur.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

_log = logging.getLogger(__name__)

# Her rerun’da kaç analist sembolü (yakıt pompası hızı)
ANALIST_BOOT_CHUNK = 12
# Aynı sembol boot’ta en fazla bu kadar denenir; sonra atlanır (Yahoo al_sayi yok)
ANALIST_BOOT_MAX_TRIES = 1
# Soft: en fazla bir analist dilimi, kalanı daemon
ANALIST_SOFT_MAX_CHUNKS = 1
# Soft unlock için kabul edilen bayat makro yaşı
SOFT_MAX_BAYAT_SN = 48 * 3600


def disk_boot_hazir(
    *,
    canli: bool = True,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
    use_signal_v2: bool = True,
) -> bool:
    """Soft açılış uygunluğu — makro VE tarama diski ≤48h taze ise.

    Yalnız makro yeterli değildi: tarama diski yoksa UI 'boş tablo' ile açılıp
    kullanıcı 30–90 sn beklerdi. Artık ikisi de gerekli; tarama yoksa/eskiyse
    film boot (ilerleme ekranı) gösterilir, son tarama arka planda tazelenir.
    """
    from disk_onbellek import TTL, disk_getir, disk_mtime

    snap, yas = disk_getir("makro:canli", TTL["makro"], bayat_kabul=True)
    if snap is None or yas is None or float(yas) > SOFT_MAX_BAYAT_SN:
        return False

    if not canli:
        # Demo modunda tarama anında üretilir — makro diski yeterli.
        return True

    try:
        from allocation_engine import tahsis_hesapla
        from investor_profile import YatirimProfili

        profil = YatirimProfili(risk=profil_risk or "orta", vade=profil_vade or "orta")
        tahsis = tahsis_hesapla(snap, profil)
        rejim = getattr(getattr(tahsis, "rejim", None), "rejim", "NOTR") or "NOTR"
    except Exception:
        rejim = "NOTR"

    # app_veri.tarama_cek ile birebir aynı anahtar (senkronize tutulmalı).
    anahtar = (
        f"tarama:{canli}:{rejim}:False:{profil_risk or 'orta'}:{profil_vade or 'orta'}"
        f":v2={int(use_signal_v2)}:gbx_v3:live_v1"
    )
    mtime = disk_mtime(anahtar)
    if mtime <= 0:
        return False
    return (time.time() - mtime) <= SOFT_MAX_BAYAT_SN


def _new_ctx(
    *,
    canli: bool,
    force: bool,
    profil_risk: str,
    profil_vade: str,
    use_signal_v2: bool,
    soft: bool = False,
) -> Dict[str, Any]:
    return {
        "phase": "fx",
        "canli": canli,
        "force": force,
        "soft": bool(soft) and not force,
        "profil_risk": profil_risk,
        "profil_vade": profil_vade,
        "use_signal_v2": use_signal_v2,
        "done_ids": [],
        "stages": {},
        "t0": time.time(),
        "rejim": "NOTR",
        "analist_fetched": 0,
        "analist_need0": 0,
        "analist_ok": 0,
        "analist_tot": 0,
        "analist_chunks": 0,
        "analist_attempts": {},
        "analist_skip": [],
        "last_detail": "Sistem başlatılıyor…",
        "last_tickers": [],
        "complete": False,
        "summary": {},
    }


def _boot_analist_need(syms: Sequence[str], *, skip: Sequence[str] = ()) -> List[str]:
    """Boot için eksik: etiket (recommendationKey) yoksa.

    al_sayi eksiği boot’u kilitlemez — arka planda tamamlanır.
    """
    from background_cache import analist_eksik_semboller
    from temel_veri import _cache_taze, yukle_cache

    skip_set = {str(s).upper() for s in (skip or [])}
    raw = analist_eksik_semboller(syms)
    cache = yukle_cache()
    out: List[str] = []
    for s in raw:
        if s in skip_set:
            continue
        ent = cache.get(s) or {}
        # Etiket taze ise boot yeterli sayar (al_sayi olmasa da)
        if (
            ent
            and _cache_taze(ent)
            and not ent.get("_bos")
            and ent.get("recommendationKey")
        ):
            continue
        out.append(s)
    return out


def boot_ui_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Kart için active / done / detail / pct + yakıt sayacı."""
    phase = ctx.get("phase") or "fx"
    done = list(ctx.get("done_ids") or [])
    detail = ctx.get("last_detail") or ""
    ticks = ctx.get("last_tickers") or []
    if ticks:
        detail = f"{detail}  ·  Son: {' · '.join(ticks[-4:])}"

    ok = int(ctx.get("analist_ok") or 0)
    tot = int(ctx.get("analist_tot") or 0)
    counter = f"{ok}/{tot}" if tot else ""

    # Faz ağırlıkları — analistte hazır/toplam ile akar
    base = {"fx": 8, "quotes": 22, "scan": 42, "analist": 55, "ready": 96, "done": 100}
    pct = float(base.get(phase, 10))
    if phase == "analist" and tot > 0:
        pct = 55.0 + 40.0 * min(1.0, ok / tot)
    if ctx.get("complete"):
        phase = "ready"
        done = ["fx", "quotes", "scan", "analist", "ready"]
        pct = 100.0
    return {
        "active_id": "ready" if ctx.get("complete") else phase,
        "done_ids": done,
        "detail": detail,
        "pct": pct,
        "counter": counter,
        "counter_label": "Analist hazır",
    }


def advance_boot(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Tek dilim ilerlet — çağıran complete değilse st.rerun() yapmalı."""
    phase = ctx.get("phase") or "fx"
    canli = bool(ctx.get("canli", True))
    force = bool(ctx.get("force", False))

    if phase == "fx":
        return _step_fx(ctx)
    if phase == "quotes":
        return _step_quotes(ctx, canli, force)
    if phase == "scan":
        return _step_scan(ctx, canli, force)
    if phase == "analist":
        return _step_analist(ctx, canli)
    if phase == "ready":
        return _step_ready(ctx)
    ctx["complete"] = True
    return ctx


def _step_fx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app_veri import cds_kaynak_ozet, veri_cek
    from allocation_engine import tahsis_hesapla
    from investor_profile import YatirimProfili

    ctx["last_detail"] = "CDS ve makro snapshot çekiliyor…"
    try:
        cds = cds_kaynak_ozet(1 if ctx.get("force") else 0)
        snap = veri_cek(bool(ctx.get("canli")), 1 if ctx.get("force") else 0)
        profil = YatirimProfili(
            risk=ctx.get("profil_risk") or "orta",
            vade=ctx.get("profil_vade") or "orta",
        )
        tahsis = tahsis_hesapla(snap, profil)
        rejim = getattr(getattr(tahsis, "rejim", None), "rejim", "NOTR") or "NOTR"
        ctx["rejim"] = rejim
        ctx["stages"]["fx"] = {
            "ok": True,
            "rejim": rejim,
            "cds": bool(cds),
            "eur_try": getattr(getattr(snap, "veri", None), "eur_try", None),
        }
        ctx["last_detail"] = (
            f"Makro hazır · rejim {rejim} · "
            f"EURTRY {getattr(snap.veri, 'eur_try', None) or '—'}"
        )
    except Exception as e:
        _log.exception("boot fx")
        ctx["stages"]["fx"] = {"ok": False, "error": str(e)}
        ctx["last_detail"] = f"Makro kısmi: {e}"
        ctx["rejim"] = "NOTR"
    ctx["done_ids"] = ["fx"]
    ctx["phase"] = "quotes"
    return ctx


def _step_quotes(ctx: Dict[str, Any], canli: bool, force: bool) -> Dict[str, Any]:
    from background_cache import ensure_quotes_daemon
    from signal_engine.data.live_quote import (
        DISK_TTL_SEC,
        live_quotes_cache_age_sec,
        load_live_quotes_disk,
    )

    ctx["last_detail"] = "Canlı kotasyon önbelleği kontrol ediliyor…"
    try:
        load_live_quotes_disk(hydrate_memory=True)
        age = live_quotes_cache_age_sec()
        need_q = force or age is None or age > DISK_TTL_SEC
        if need_q and canli:
            # Hiçbir boot'ta bloklama yok — disk hydrate + arka plan daemon
            # (soğuk/force dahil). Kararlar günlük barlara dayanır; canlı fiyat
            # SWR (allow_stale) ile okunur, 15 dk bayatlık zaten kabul ediliyor.
            started = ensure_quotes_daemon()
            ctx["stages"]["quotes"] = {
                "ok": True,
                "refreshed": False,
                "soft": True,
                "daemon": started,
                "age_sec": age,
            }
            ctx["last_detail"] = (
                "Canlı fiyat son kayıt"
                + (f" · yaş {age:.0f}s" if age is not None else "")
                + (" · arka planda tazeleniyor" if started or age is None else "")
            )
        else:
            ctx["stages"]["quotes"] = {"ok": True, "refreshed": False, "age_sec": age}
            ctx["last_detail"] = (
                f"Canlı fiyat taze · yaş {age:.0f}s"
                if age is not None
                else "Canlı fiyat hazır"
            )
    except Exception as e:
        _log.exception("boot quotes")
        ctx["stages"]["quotes"] = {"ok": False, "error": str(e)}
        ctx["last_detail"] = f"Canlı fiyat uyarısı: {e}"
    ctx["done_ids"] = ["fx", "quotes"]
    ctx["phase"] = "scan"
    return ctx


def _step_scan(ctx: Dict[str, Any], canli: bool, force: bool) -> Dict[str, Any]:
    from app_veri import tarama_cek, tarama_yukleniyor, veri_cek

    ctx["last_detail"] = "Hisse / ETF taraması — barlar ve teknik…"
    try:
        snap = veri_cek(canli, 1 if force else 0)
        tarama = tarama_cek(
            canli,
            ctx.get("rejim") or "NOTR",
            getattr(snap, "veri_kaynak", "") or "",
            1 if force else 0,
            haber_tara=False,
            profil_risk=ctx.get("profil_risk") or "orta",
            profil_vade=ctx.get("profil_vade") or "orta",
            zorla=force,
            use_signal_v2=bool(ctx.get("use_signal_v2", True)),
        )
        yukleniyor = tarama_yukleniyor(tarama)
        n = len(getattr(tarama, "hisseler", None) or [])
        ctx["stages"]["scan"] = {
            "ok": not yukleniyor and n > 0,
            "n_hisse": n,
            "loading": yukleniyor,
        }
        if yukleniyor:
            ctx["last_detail"] = "Tarama arka planda — tablolar dolunca güncellenir"
        else:
            ctx["last_detail"] = f"Tarama hazır · {n} varlık · Signal Engine"
    except Exception as e:
        _log.exception("boot scan")
        ctx["stages"]["scan"] = {"ok": False, "error": str(e)}
        ctx["last_detail"] = f"Tarama uyarısı: {e}"
    ctx["done_ids"] = ["fx", "quotes", "scan"]
    ctx["phase"] = "analist"
    return ctx


def _step_analist(ctx: Dict[str, Any], canli: bool) -> Dict[str, Any]:
    from background_cache import (
        analist_hazir_say,
        ensure_analist_batch_daemon,
        refresh_analist_misses,
        universe_analist_symbols,
    )

    soft = bool(ctx.get("soft")) and not bool(ctx.get("force"))

    if not canli:
        ctx["stages"]["analist"] = {"ok": True, "skipped": True}
        ctx["last_detail"] = "Demo — analist atlandı"
        ctx["done_ids"] = ["fx", "quotes", "scan", "analist"]
        ctx["phase"] = "ready"
        return ctx

    syms = universe_analist_symbols()
    skip = list(ctx.get("analist_skip") or [])
    attempts: Dict[str, int] = dict(ctx.get("analist_attempts") or {})
    need = _boot_analist_need(syms, skip=skip)
    ok0, tot = analist_hazir_say(syms)
    ctx["analist_ok"] = ok0
    ctx["analist_tot"] = tot
    if not ctx.get("analist_need0"):
        ctx["analist_need0"] = max(len(need), 1)

    if not need:
        n_skip = len(skip)
        ctx["stages"]["analist"] = {
            "ok": True, "before": ok0, "after": ok0, "total": tot,
            "skipped": n_skip, "fetched": ctx.get("analist_fetched", 0),
        }
        ctx["last_detail"] = (
            f"Analist {ok0}/{tot} hazır"
            + (f" · {n_skip} sembol kısmi (arka planda)" if n_skip else "")
        )
        ctx["done_ids"] = ["fx", "quotes", "scan", "analist"]
        ctx["phase"] = "ready"
        return ctx

    # Soft: dilim kotası dolduysa ready — kalan daemon
    chunks_done = int(ctx.get("analist_chunks") or 0)
    if soft and chunks_done >= ANALIST_SOFT_MAX_CHUNKS:
        try:
            ensure_analist_batch_daemon(syms)
        except Exception:
            pass
        ctx["stages"]["analist"] = {
            "ok": True,
            "soft": True,
            "after": ok0,
            "total": tot,
            "remaining": len(need),
            "fetched": ctx.get("analist_fetched", 0),
        }
        ctx["last_detail"] = (
            f"Analist {ok0}/{tot} · kalan {len(need)} arka planda"
        )
        ctx["done_ids"] = ["fx", "quotes", "scan", "analist"]
        ctx["phase"] = "ready"
        return ctx

    chunk = need[:ANALIST_BOOT_CHUNK]
    ctx["last_detail"] = (
        f"Analist {ok0}→{min(ok0 + len(chunk), tot)}/{tot} · dilim {len(chunk)}"
    )
    last_syms: List[str] = []

    def _prog(done: int, total: int, mesaj: str) -> None:
        parca = mesaj.split(":")[-1].strip() if ":" in mesaj else mesaj
        ticker = parca.split()[0] if parca else ""
        if ticker and ticker not in ("Başlıyor…", "Tamamlandı", "?"):
            last_syms.append(ticker)
            ctx["last_tickers"] = (list(ctx.get("last_tickers") or []) + [ticker])[-4:]
        # Yakıt pompası: anlık hazır sayısı
        approx = min(tot, ok0 + done)
        ctx["analist_ok"] = approx
        ctx["last_detail"] = f"Analist {approx}/{tot} · {ticker or mesaj}"

    try:
        astat = refresh_analist_misses(
            chunk,  # yalnız bu dilim — gereksiz tarama yok
            max_workers=4,
            batch_limit=len(chunk),
            log=lambda m: _log.info(m),
            progress_cb=_prog,
        )
        ctx["analist_fetched"] = int(ctx.get("analist_fetched") or 0) + int(
            astat.get("fetched") or len(chunk)
        )
        ctx["analist_chunks"] = chunks_done + 1
        ok1, tot = analist_hazir_say(syms)
        ctx["analist_ok"] = ok1
        ctx["analist_tot"] = tot

        # Hâlâ etiketsiz kalanları dene sayacı / atla
        still = set(_boot_analist_need(syms, skip=skip))
        for s in chunk:
            attempts[s] = int(attempts.get(s, 0)) + 1
            if s in still and attempts[s] >= ANALIST_BOOT_MAX_TRIES:
                skip.append(s)
        ctx["analist_attempts"] = attempts
        ctx["analist_skip"] = list(dict.fromkeys(skip))

        left = _boot_analist_need(syms, skip=ctx["analist_skip"])
        if last_syms:
            ctx["last_tickers"] = (list(ctx.get("last_tickers") or []) + last_syms[-2:])[-4:]
        ctx["last_detail"] = (
            f"Analist {ok1}/{tot} · kalan {len(left)}"
            + (f" · {last_syms[-1]}" if last_syms else "")
        )
        ctx["stages"]["analist"] = {
            "ok": True,
            "after": ok1,
            "total": tot,
            "remaining": len(left),
            "skipped": len(ctx["analist_skip"]),
            "fetched": ctx["analist_fetched"],
        }
        if not left or (soft and int(ctx.get("analist_chunks") or 0) >= ANALIST_SOFT_MAX_CHUNKS):
            if left and soft:
                try:
                    ensure_analist_batch_daemon(syms)
                except Exception:
                    pass
                ctx["last_detail"] = (
                    f"Analist {ok1}/{tot} · kalan {len(left)} arka planda"
                )
            ctx["done_ids"] = ["fx", "quotes", "scan", "analist"]
            ctx["phase"] = "ready"
    except Exception as e:
        _log.exception("boot analist")
        ctx["stages"]["analist"] = {"ok": False, "error": str(e)}
        ctx["last_detail"] = f"Analist uyarısı: {e}"
        ctx["done_ids"] = ["fx", "quotes", "scan", "analist"]
        ctx["phase"] = "ready"
    return ctx


def _step_ready(ctx: Dict[str, Any]) -> Dict[str, Any]:
    elapsed = time.time() - float(ctx.get("t0") or time.time())
    ctx["last_detail"] = f"Sistem hazır · {elapsed:.0f}s — paneller açılıyor"
    ctx["done_ids"] = ["fx", "quotes", "scan", "analist", "ready"]
    ctx["complete"] = True
    ctx["phase"] = "done"
    ctx["summary"] = {
        "ok": True,
        "force": bool(ctx.get("force")),
        "soft": bool(ctx.get("soft")),
        "stages": dict(ctx.get("stages") or {}),
        "elapsed_sec": elapsed,
    }
    return ctx


# Geriye uyum — tek seferde (testler); UI için advance_boot tercih edin
def run_boot_sequence(
    *,
    canli: bool = True,
    force: bool = False,
    soft: bool = False,
    status_cb=None,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
    use_signal_v2: bool = True,
) -> dict:
    ctx = _new_ctx(
        canli=canli,
        force=force,
        soft=soft,
        profil_risk=profil_risk,
        profil_vade=profil_vade,
        use_signal_v2=use_signal_v2,
    )
    guard = 0
    while not ctx.get("complete") and guard < 500:
        guard += 1
        ctx = advance_boot(ctx)
        ui = boot_ui_state(ctx)
        if status_cb:
            status_cb(ui["active_id"], ui["done_ids"], ui["detail"], ui["pct"])
    return ctx.get("summary") or {"ok": False, "elapsed_sec": 0}
