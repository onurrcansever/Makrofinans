# -*- coding: utf-8 -*-
"""EndeksAI — endeks tablosu yorumu (skora girmez; ayrı cache)."""
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
    ".llm_endeks_cache.json",
)

TTL_HOURS = 24
API_TIMEOUT_SEC = 10.0
MAX_PER_MINUTE = 8
FALLBACK = "Endeks açıklaması şu an mevcut değil"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 650

_rate_ts: List[float] = []


def _bugun() -> str:
    return date.today().isoformat()


def _parse_gun(s: str) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def cache_anahtar(fingerprint: str, gpb: str) -> str:
    return f"ENDEKS|{_bugun()}|{(gpb or 'EUR').upper()}|{(fingerprint or '')[:16]}"


def yukle_cache() -> Dict[str, dict]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        _log.warning("llm_endeks cache okunamadı: %s", e)
        return {}


def kaydet_cache(cache: Dict[str, dict]) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".llm_endeks.", suffix=".tmp", dir=directory)
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


def _snapshot_text(snap: Any) -> str:
    if snap is None:
        return ""
    if hasattr(snap, "prompt_block") and callable(snap.prompt_block):
        return str(snap.prompt_block())
    if isinstance(snap, dict):
        from signal_engine.explain.endeks_snapshot import EndeksSnapshot, EndeksSatirSnap

        satirlar = []
        for row in snap.get("satirlar") or []:
            if isinstance(row, dict):
                satirlar.append(EndeksSatirSnap(**{
                    k: row.get(k) for k in EndeksSatirSnap.__dataclass_fields__
                }))
        s = EndeksSnapshot(
            oncelik=snap.get("oncelik") or "",
            gosterim_pb=snap.get("gosterim_pb") or "EUR",
            satirlar=satirlar,
            lejant=snap.get("lejant") or "",
            okuma_sirasi=snap.get("okuma_sirasi") or "",
            makro_rejim=snap.get("makro_rejim") or "",
        )
        return s.prompt_block()
    return str(snap)


def _build_prompt(snap: Any) -> str:
    block = _snapshot_text(snap)
    return f"""Sen deneyimli bir endeks / platform ağırlığı yorumcususun.
Aşağıdaki VERİYE dayanarak Türkçe detaylı bir EndeksAI notu yaz (8–12 cümle).
Ton: pratik — «şu platforma ağırlık / şunu tut / BIST’te seçici ol».

{block}

ZORUNLU AKIŞ (başlıksız düz cümleler):
1) Bugün bakılacak yer / öncelik bandı — ne anlama geliyor
2) Her endeks satırı: Öneri (Artır/Koru/Bekle/Azalt) = pozisyon ağırlığı diliyle
3) BIST Azalt veya Bekle iken o pazarda hisse AL çıkabilir → seçici/küçük; veto değil
4) Tablodaki gösterim PB (ör. EUR) vs yerel karar — çelişki varsa açıkla
5) Okuma sırası: makro → endeks → hisse «Şimdi ne yap?»
6) Bugün için somut: hangi platforma ağırlık / neyi beklemeli / temkin
7) Kısa risk cümlesi

KURALLAR:
- Sadece VERİ'deki endeks/rakam; uydurma ticker veya endeks yok
- Haber uydurma; MACD/haftalık yoksa yazma
- "Kesinlikle al/sat" deme — değerlendir / tut / azalt / bekle dili
- Koru'yu hisse İZLE sanma; Azalt'ı tüm BIST AL iptali sanma
- 8–12 cümle; yasal uyarı ekleme (ayrıca gösterilecek)
"""


def _call_llm(prompt: str, *, api_key: Optional[str] = None) -> str:
    from llm_shared import call_llm_default

    text = call_llm_default(
        prompt,
        max_tokens=MAX_TOKENS,
        timeout=API_TIMEOUT_SEC,
        api_key=api_key,
    )
    return (text or "").strip() or FALLBACK


def endeks_aciklamasi(
    snap: Any,
    *,
    gosterim_pb: str = "EUR",
    force: bool = False,
    timeout: float = API_TIMEOUT_SEC,
    api_key: Optional[str] = None,
    _call_fn=None,
) -> Tuple[str, Dict[str, Any]]:
    """(metin, meta). snap: EndeksSnapshot veya dict."""
    from llm_shared import aktif_model_meta

    fp = ""
    if hasattr(snap, "cache_fingerprint"):
        fp = snap.cache_fingerprint()
    elif isinstance(snap, dict):
        fp = str(hash(json.dumps(snap, sort_keys=True, default=str)))[:16]
    key = cache_anahtar(fp, gosterim_pb)
    cache = yukle_cache()
    am = aktif_model_meta()
    meta: Dict[str, Any] = {
        "cache_hit": False,
        "guncelleme": _bugun(),
        "model": am.get("model") or MODEL,
        "provider": am.get("provider") or "",
        "anahtar": key,
        "hint": "EndeksAI",
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

    prompt = _build_prompt(snap)
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
        _log.warning("llm_endeks timeout %.1fs", timeout)
        meta["hata"] = "timeout"
        return FALLBACK, meta
    except Exception as e:
        _log.warning("llm_endeks: %s", e)
        meta["hata"] = str(e)
        return FALLBACK, meta

    _rate_limit_hit()
    metin = (metin or "").strip() or FALLBACK
    cache[key] = {
        "metin": metin,
        "guncelleme": _bugun(),
        "model": meta["model"],
        "provider": meta.get("provider") or "",
        "fingerprint": fp,
    }
    try:
        kaydet_cache(cache)
    except Exception as e:
        _log.warning("llm_endeks cache yazılamadı: %s", e)
    meta["cache_hit"] = False
    return metin, meta


def format_endeks_ai_markdown(metin: str, meta: Optional[dict] = None) -> str:
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
    src = meta.get("hint") or meta.get("provider") or meta.get("model") or "EndeksAI"
    return (
        "### EndeksAI\n\n"
        f"{metin}\n\n"
        f"[{src} · {gun_tr}]"
    )


def clear_rate_limit_for_tests() -> None:
    global _rate_ts
    _rate_ts = []
