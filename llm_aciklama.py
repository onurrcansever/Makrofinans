# -*- coding: utf-8 -*-
"""
Aşama 2B — Claude ile hisse açıklaması (Neden? paneli, tıklanınca).
Skora girmez; cache + rate limit korumalı.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".llm_aciklama_cache.json",
)

TTL_HOURS = 24
API_TIMEOUT_SEC = 5.0
MAX_PER_MINUTE = 10
FALLBACK = "Açıklama şu an mevcut değil"
MODEL = "claude-sonnet-4-6"

# Süreç içi rate limit (timestamp listesi)
_rate_ts: List[float] = []


def _bugun() -> str:
    return date.today().isoformat()


def _parse_gun(s: str) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def cache_anahtar(sembol: str, karar: str, skor: float) -> str:
    return f"{(sembol or '').strip().upper()}|{(karar or '').strip()}|{int(round(float(skor or 0)))}"


def yukle_cache() -> Dict[str, dict]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        _log.warning("llm_aciklama cache okunamadı: %s", e)
        return {}


def kaydet_cache(cache: Dict[str, dict]) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".llm_aciklama.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _cache_taze(entry: dict, *, now: Optional[date] = None) -> bool:
    g = _parse_gun(entry.get("guncelleme", ""))
    if g is None:
        return False
    ref = now or date.today()
    return (ref - g) < timedelta(hours=TTL_HOURS)


def _rate_limit_ok() -> bool:
    now = time.time()
    global _rate_ts
    _rate_ts = [t for t in _rate_ts if now - t < 60.0]
    return len(_rate_ts) < MAX_PER_MINUTE


def _rate_limit_hit() -> None:
    _rate_ts.append(time.time())


def _format_temel(temel: dict) -> str:
    if not temel:
        return "Temel veri yok"
    if temel.get("tur") == "etf":
        return "ETF — temel analiz verisi yok"
    satirlar = []
    if temel.get("fk_trailing") is not None:
        ff = temel.get("fk_forward")
        ff_s = f"{ff:.1f}" if isinstance(ff, (int, float)) else "?"
        satirlar.append(
            f"- F/K: {temel['fk_trailing']:.1f}x (ileri: {ff_s}x)"
        )
    if temel.get("analist"):
        n = temel.get("analist_sayi") or "?"
        satirlar.append(f"- Analist: {n} → {temel['analist']}")
    if temel.get("hedef_fark_pct") is not None:
        satirlar.append(f"- Hedef: {temel['hedef_fark_pct']:+.1f}%")
    if temel.get("buyume"):
        satirlar.append(f"- Büyüme: {temel['buyume']}")
    return "\n".join(satirlar) if satirlar else "Temel veri yok"


def _faktor_al(faktorler: dict, *keys: str) -> Any:
    for k in keys:
        if faktorler and k in faktorler and faktorler[k] is not None:
            return faktorler[k]
    return "—"


def _build_prompt(
    sembol: str,
    karar: str,
    skor: int,
    faktorler: dict,
    temel: dict,
    fiyat_eur: float,
    getiri_1y: float,
    rejim: str,
) -> str:
    return f"""Sen bir portföy analiz asistanısın. Aşağıdaki verilere dayanarak
{sembol} için 2-3 cümlelik Türkçe bir yatırım notu yaz.

Teknik sinyal:
- Karar: {karar} (skor: {skor}/100)
- Trend: {_faktor_al(faktorler, 'trend')}/100
- Momentum: {_faktor_al(faktorler, 'mean_reversion', 'mean_rev')}/100
- Volatilite: {_faktor_al(faktorler, 'volatility', 'vol')}/100
- Göreli güç: {_faktor_al(faktorler, 'relative_strength', 'rel')}/100
- Likidite: {_faktor_al(faktorler, 'liquidity', 'lik')}/100
- Rejim: {rejim}

Temel veriler:
{_format_temel(temel)}

Fiyat: {fiyat_eur:.2f} EUR | 1Y getiri: {getiri_1y:+.1f}%

KURALLAR:
- Sadece verilen verilere dayan, tahmin yapma
- "Kesinlikle al/sat" deme — olasılık dili kullan
- Çelişki varsa belirt (ör: teknik zayıf ama analist güçlü al)
- Maksimum 3 cümle
- Yasal uyarı ekleme (ayrıca gösterilecek)
"""


def _call_llm(prompt: str, *, api_key: Optional[str] = None) -> str:
    from llm_shared import aktif_model_meta, call_llm_default

    text = call_llm_default(
        prompt,
        max_tokens=200,
        timeout=API_TIMEOUT_SEC,
        api_key=api_key,
    )
    return (text or "").strip() or FALLBACK


def hisse_aciklamasi(
    sembol: str,
    karar: str,
    skor: int,
    faktorler: dict,
    temel: dict,
    fiyat_eur: float,
    getiri_1y: float,
    rejim: str,
    *,
    force: bool = False,
    timeout: float = API_TIMEOUT_SEC,
    api_key: Optional[str] = None,
    _call_fn=None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Dönüş: (metin, meta) — meta: cache_hit, guncelleme, model, hata.
    _call_fn: test mock (prompt -> str).
    """
    from llm_shared import aktif_model_meta

    key = cache_anahtar(sembol, karar, skor)
    cache = yukle_cache()
    am = aktif_model_meta()
    meta: Dict[str, Any] = {
        "cache_hit": False,
        "guncelleme": _bugun(),
        "model": am.get("model") or MODEL,
        "provider": am.get("provider") or "",
        "anahtar": key,
    }

    if not force:
        ent = cache.get(key)
        if ent and _cache_taze(ent) and ent.get("metin"):
            meta["cache_hit"] = True
            meta["guncelleme"] = ent.get("guncelleme") or _bugun()
            meta["model"] = ent.get("model") or meta["model"]
            return str(ent["metin"]), meta

    if not _rate_limit_ok():
        meta["hata"] = "rate_limit"
        return FALLBACK, meta

    prompt = _build_prompt(
        sembol, karar, int(round(skor)),
        faktorler or {}, temel or {},
        float(fiyat_eur or 0), float(getiri_1y or 0), rejim or "—",
    )
    call = _call_fn or _call_llm

    def _run():
        if _call_fn is not None:
            return call(prompt)
        return call(prompt, api_key=api_key)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run)
            metin = fut.result(timeout=timeout)
    except FutTimeout:
        _log.warning("llm_aciklama %s: timeout %.1fs", sembol, timeout)
        meta["hata"] = "timeout"
        return FALLBACK, meta
    except Exception as e:
        _log.warning("llm_aciklama %s: %s", sembol, e)
        meta["hata"] = str(e)
        return FALLBACK, meta

    _rate_limit_hit()
    metin = (metin or "").strip() or FALLBACK
    cache[key] = {
        "metin": metin,
        "guncelleme": _bugun(),
        "sembol": (sembol or "").upper(),
        "karar": karar,
        "skor": int(round(skor)),
        "model": meta["model"],
        "provider": meta.get("provider") or "",
    }
    try:
        kaydet_cache(cache)
    except Exception as e:
        _log.warning("llm_aciklama cache yazılamadı: %s", e)
    meta["cache_hit"] = False
    return metin, meta


def format_ai_markdown(metin: str, meta: Optional[dict] = None) -> str:
    meta = meta or {}
    gun = meta.get("guncelleme") or _bugun()
    try:
        d = datetime.strptime(str(gun)[:10], "%Y-%m-%d")
        aylar = (
            "Oca", "Şub", "Mar", "Nis", "May", "Haz",
            "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
        )
        gun_tr = f"{d.day} {aylar[d.month - 1]} {d.year}"
    except ValueError:
        gun_tr = gun
    src = meta.get("hint") or meta.get("provider") or meta.get("model") or "AI"
    return (
        "### ✨ AI Analiz\n\n"
        f"{metin}\n\n"
        f"[{src} · {gun_tr}]"
    )


def clear_rate_limit_for_tests() -> None:
    global _rate_ts
    _rate_ts = []
