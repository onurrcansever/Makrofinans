# -*- coding: utf-8 -*-
"""Ortak LLM yardımcıları — cache I/O + hata metinleri + provider çözümü."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from llm_client import provider_hint, provider_ready, resolve_model, resolve_provider

_log = logging.getLogger(__name__)

HATA_NO_KEY = "LLM anahtarı yok"
HATA_RATE = "Dakikalık istek limiti"
HATA_403 = "Groq erişim engeli — yenileyip tekrar deneyin"
HATA_401 = "API anahtarı geçersiz — `.env` kontrol edin"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def bugun() -> str:
    return date.today().isoformat()


def parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        raw = str(s).strip()
        if len(raw) == 10:
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def cache_taze_saat(entry: dict, *, ttl_hours: float, now: Optional[datetime] = None) -> bool:
    dt = parse_ts(str(entry.get("guncelleme") or ""))
    if dt is None:
        return False
    ref = now or now_utc()
    return (ref - dt) < timedelta(hours=float(ttl_hours))


def cache_taze_gun(entry: dict, *, ttl_hours: float = 24.0, now: Optional[date] = None) -> bool:
    """Gün bazlı TTL (llm_aciklama uyumu)."""
    g = parse_ts(str(entry.get("guncelleme") or ""))
    if g is None:
        return False
    ref = now or date.today()
    gun = g.date() if hasattr(g, "date") else g
    return (ref - gun) < timedelta(hours=float(ttl_hours))


def yukle_json_cache(path: str) -> Dict[str, dict]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        _log.warning("cache okunamadı %s: %s", path, e)
        return {}


def kaydet_json_cache(path: str, cache: Dict[str, dict], *, prefix: str = ".llm.") -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def aktif_model_meta() -> Dict[str, str]:
    p = resolve_provider()
    return {
        "provider": p,
        "model": resolve_model(p),
        "hint": provider_hint(),
        "ready": "1" if provider_ready() else "0",
    }


def hata_metni(err: Any, *, fallback: str) -> str:
    s = str(err or "")
    if "429" in s or "daily_quota" in s:
        return (
            f"{fallback} (Groq günlük token kotası doldu — "
            "birkaç saat/yarın veya LLM_MODEL=llama-3.1-8b-instant)"
        )
    if "403" in s or "1010" in s:
        return f"{fallback} ({HATA_403})"
    if "401" in s:
        return f"{fallback} ({HATA_401})"
    if "rate_limit" in s:
        return f"{fallback} ({HATA_RATE})"
    if "anahtar" in s.lower() or "no_key" in s or "LLM anahtarı" in s:
        return f"{fallback} {provider_hint()}"
    return fallback


def call_llm_default(
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
    api_key: Optional[str] = None,
    _call_fn=None,
) -> str:
    """resolve_provider() ile çağrı — Anthropic zorlaması yok."""
    from llm_client import call_chat

    if _call_fn is not None:
        return (_call_fn(prompt) or "").strip()
    return call_chat(
        prompt,
        max_tokens=max_tokens,
        timeout=timeout,
        api_key=api_key,
    )
