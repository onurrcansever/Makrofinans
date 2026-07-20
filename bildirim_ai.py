# -*- coding: utf-8 -*-
"""Sinyal alarmı için kısa AI özeti — başarısızsa sessizce None."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from llm_client import provider_ready
from llm_shared import (
    aktif_model_meta,
    bugun,
    cache_taze_saat,
    call_llm_default,
    kaydet_json_cache,
    now_utc,
    yukle_json_cache,
)

_log = logging.getLogger(__name__)

STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".bildirim_ai_cache.json",
)
TTL_HOURS = 12.0
API_TIMEOUT_SEC = 6.0
MAX_OLAY = 5


def _olay_imza(olaylar: Sequence[Tuple[str, str, Any]], rejim: str) -> str:
    parts = [str(rejim or "")]
    for tip, sym, _h in list(olaylar)[:MAX_OLAY]:
        parts.append(f"{tip}:{sym}")
    blob = "|".join(parts) + "|" + bugun()
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _olay_ozet(olaylar: Sequence[Tuple[str, str, Any]]) -> List[dict]:
    out = []
    for tip, sym, h in list(olaylar)[:MAX_OLAY]:
        skor = getattr(h, "signal_v2_score", None)
        if skor is None:
            skor = getattr(h, "skor", None)
        out.append({
            "tip": tip,
            "sembol": sym,
            "ad": (getattr(h, "ad", "") or "")[:30],
            "skor": round(float(skor or 0), 0) if skor is not None else None,
            "sinyal": getattr(h, "sinyal", "") or "",
        })
    return out


def _build_prompt(*, rejim: str, vix: Any, olaylar: List[dict]) -> str:
    veri = json.dumps({"rejim": rejim, "vix": vix, "olaylar": olaylar}, ensure_ascii=False)
    return f"""Sinyal alarmı özeti yaz. En fazla 2 kısa Türkçe cümle.
Sadece verilen olaylara dayan; uydurma sembol ekleme; "kesinlikle al/sat" deme.
Yasal uyarı ekleme.

VERİ: {veri}
"""


def bildirim_ai_ozet(
    olaylar: Sequence[Tuple[str, str, Any]],
    *,
    rejim: str = "",
    vix: Any = None,
    force: bool = False,
    _call_fn=None,
) -> Optional[str]:
    """1–2 cümle; yoksa None (alarm yine gönderilir)."""
    if not olaylar:
        return None
    key = _olay_imza(olaylar, rejim)
    cache = yukle_json_cache(STATE_PATH)
    if not force:
        ent = cache.get(key)
        if ent and cache_taze_saat(ent, ttl_hours=TTL_HOURS) and ent.get("metin"):
            return str(ent["metin"]).strip() or None

    if not provider_ready() and _call_fn is None:
        return None

    prompt = _build_prompt(rejim=rejim, vix=vix, olaylar=_olay_ozet(olaylar))
    try:
        metin = call_llm_default(
            prompt,
            max_tokens=120,
            timeout=API_TIMEOUT_SEC,
            _call_fn=_call_fn,
        )
    except Exception as e:
        _log.warning("bildirim_ai_ozet: %s", e)
        return None

    metin = (metin or "").strip()
    if not metin:
        return None
    # Tek satırlaştır; yasal uyarı sızıntısını kes
    metin = " ".join(metin.split())
    for kes in ("Yasal Uyarı", "yasal uyarı", "yatırım tavsiyesi değildir"):
        if kes in metin:
            metin = metin.split(kes)[0].strip(" .;")
    if len(metin) > 280:
        metin = metin[:277] + "…"
    if not metin:
        return None

    am = aktif_model_meta()
    cache[key] = {
        "metin": metin,
        "guncelleme": now_utc().isoformat(),
        "model": am.get("model"),
        "provider": am.get("provider"),
    }
    try:
        kaydet_json_cache(STATE_PATH, cache, prefix=".bildirim_ai.")
    except Exception as e:
        _log.warning("bildirim_ai cache yazılamadı: %s", e)
    return metin
