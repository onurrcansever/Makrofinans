# -*- coding: utf-8 -*-
"""Ortak LLM istemcisi — Groq (ücretsiz, OpenAI-uyumlu) + Anthropic yedek."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence
import tempfile

_log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_SEC = 8.0
MAX_PER_MINUTE = 10
# Ücretsiz tier tipik TPD (header'da yok — yerel tahmin + 429 gövdesi)
DEFAULT_TPD_LIMIT = 100_000

QUOTA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".groq_quota.json",
)

_rate_ts: List[float] = []
_last_quota: Dict[str, Any] = {}

ChatMessage = Dict[str, str]


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def groq_key() -> str:
    k = _env("GROQ_API_KEY")
    if not k or k.startswith("your_"):
        return ""
    return k


def anthropic_key() -> str:
    k = _env("ANTHROPIC_API_KEY")
    if not k or k.startswith("your_"):
        return ""
    return k


def resolve_provider() -> str:
    """LLM_PROVIDER veya anahtar varlığına göre: groq | anthropic | none."""
    forced = _env("LLM_PROVIDER").lower()
    if forced in ("groq", "anthropic"):
        if forced == "groq" and groq_key():
            return "groq"
        if forced == "anthropic" and anthropic_key():
            return "anthropic"
        # zorlanmış ama anahtar yok → diğerine düş
    if groq_key():
        return "groq"
    if anthropic_key():
        return "anthropic"
    return "none"


def resolve_model(provider: Optional[str] = None) -> str:
    p = provider or resolve_provider()
    override = _env("LLM_MODEL")
    if override:
        return override
    if p == "anthropic":
        return DEFAULT_ANTHROPIC_MODEL
    return DEFAULT_GROQ_MODEL


def resolve_fallback_model(provider: Optional[str] = None) -> str:
    """429 / kota için yedek model (Groq)."""
    p = provider or resolve_provider()
    override = _env("LLM_MODEL_FALLBACK")
    if override:
        return override
    if p == "groq":
        primary = resolve_model("groq")
        if primary != DEFAULT_GROQ_FALLBACK_MODEL:
            return DEFAULT_GROQ_FALLBACK_MODEL
        return "llama-3.1-8b-instant"
    return ""


def provider_ready() -> bool:
    return resolve_provider() != "none"


def provider_hint() -> str:
    """UI için tek satır kurulum ipucu."""
    p = resolve_provider()
    if p == "groq":
        return f"Groq · {resolve_model('groq')}"
    if p == "anthropic":
        return f"Claude · {resolve_model('anthropic')}"
    return (
        "AI anahtarı yok — `.env` içine `GROQ_API_KEY=` ekleyin "
        "(ücretsiz: console.groq.com)"
    )


def _rate_limit_ok() -> bool:
    now = time.time()
    global _rate_ts
    _rate_ts = [t for t in _rate_ts if now - t < 60.0]
    return len(_rate_ts) < MAX_PER_MINUTE


def _rate_limit_hit() -> None:
    _rate_ts.append(time.time())


def clear_rate_limit_for_tests() -> None:
    global _rate_ts
    _rate_ts = []


def _bugun() -> str:
    return date.today().isoformat()


def _quota_yukle() -> Dict[str, Any]:
    if not os.path.isfile(QUOTA_PATH):
        return {}
    try:
        with open(QUOTA_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _quota_kaydet(data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(QUOTA_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".groq_quota.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, QUOTA_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)


def _header_get(headers, *names: str) -> str:
    if headers is None:
        return ""
    for n in names:
        try:
            v = headers.get(n)
            if v:
                return str(v).strip()
        except Exception:
            pass
        # case-insensitive
        try:
            for k in headers.keys():
                if str(k).lower() == n.lower():
                    return str(headers.get(k)).strip()
        except Exception:
            pass
    return ""


def _parse_int(s: Any) -> Optional[int]:
    try:
        if s is None or s == "":
            return None
        return int(float(str(s).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _update_quota_from_headers(headers, *, model: str = "", usage: Optional[dict] = None) -> None:
    """Groq: remaining-requests=RPD, remaining-tokens=TPM (TPD header'da yok)."""
    global _last_quota
    snap: Dict[str, Any] = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "gun": _bugun(),
        "model": model or resolve_model("groq"),
        "rpd_kalan": _parse_int(_header_get(headers, "x-ratelimit-remaining-requests")),
        "rpd_limit": _parse_int(_header_get(headers, "x-ratelimit-limit-requests")),
        "tpm_kalan": _parse_int(_header_get(headers, "x-ratelimit-remaining-tokens")),
        "tpm_limit": _parse_int(_header_get(headers, "x-ratelimit-limit-tokens")),
        "rpd_reset": _header_get(headers, "x-ratelimit-reset-requests"),
        "tpm_reset": _header_get(headers, "x-ratelimit-reset-tokens"),
    }
    disk = _quota_yukle()
    if disk.get("gun") != _bugun():
        disk = {"gun": _bugun(), "tpd_kullanilan_tahmini": 0, "tpd_limit": DEFAULT_TPD_LIMIT}
    if usage:
        tot = usage.get("total_tokens")
        if tot is None:
            try:
                tot = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
            except (TypeError, ValueError):
                tot = 0
        try:
            disk["tpd_kullanilan_tahmini"] = int(disk.get("tpd_kullanilan_tahmini") or 0) + int(tot or 0)
        except (TypeError, ValueError):
            pass
    # 429 gövdesinden TPD bilindiysa
    if snap.get("tpd_kalan") is None and disk.get("tpd_kalan") is not None:
        snap["tpd_kalan"] = disk.get("tpd_kalan")
    if snap.get("tpd_limit") is None:
        snap["tpd_limit"] = disk.get("tpd_limit") or DEFAULT_TPD_LIMIT
    snap["tpd_kullanilan_tahmini"] = disk.get("tpd_kullanilan_tahmini") or 0
    disk.update({k: v for k, v in snap.items() if v is not None and k != "guncelleme"})
    disk["guncelleme"] = snap["guncelleme"]
    _last_quota = dict(disk)
    try:
        _quota_kaydet(disk)
    except Exception as e:
        _log.warning("groq quota yazılamadı: %s", e)


def _update_quota_from_429_body(body: str, headers=None) -> None:
    """Örn: tokens per day (TPD): Limit 100000, Used 97066"""
    import re

    global _last_quota
    if headers is not None:
        _update_quota_from_headers(headers, model=resolve_model("groq"))
    m = re.search(
        r"tokens per day\s*\(TPD\)[^0-9]*Limit\s*(\d+)[^0-9]*Used\s*(\d+)",
        body or "",
        re.I,
    )
    disk = _quota_yukle()
    if disk.get("gun") != _bugun():
        disk = {"gun": _bugun(), "tpd_kullanilan_tahmini": 0}
    if m:
        lim = int(m.group(1))
        used = int(m.group(2))
        disk["tpd_limit"] = lim
        disk["tpd_kalan"] = max(0, lim - used)
        disk["tpd_kullanilan"] = used
        disk["tpd_kaynak"] = "429"
    disk["son_429"] = datetime.now(timezone.utc).isoformat()
    disk["guncelleme"] = disk["son_429"]
    disk["gun"] = _bugun()
    _last_quota = dict(disk)
    try:
        _quota_kaydet(disk)
    except Exception:
        pass


def groq_kota_ozeti() -> Dict[str, Any]:
    """UI için son bilinen Groq kota anlık görüntüsü."""
    global _last_quota
    if not _last_quota:
        _last_quota = _quota_yukle()
    q = dict(_last_quota or {})
    if q.get("gun") and q.get("gun") != _bugun():
        # Yeni gün — RPD/TPD sıfırlanmış sayılır; TPM anlık
        q = {
            "gun": _bugun(),
            "tpd_kullanilan_tahmini": 0,
            "tpd_limit": q.get("tpd_limit") or DEFAULT_TPD_LIMIT,
            "not": "Yeni gün — kota sıfırlanmış olabilir",
        }
    return q


def provider_kota_caption() -> str:
    """Tek satır: Asistan / Karar üstü."""
    p = resolve_provider()
    if p != "groq":
        return provider_hint()
    q = groq_kota_ozeti()
    parts = [f"Groq · {resolve_model('groq')}"]
    rpd = q.get("rpd_kalan")
    rpd_l = q.get("rpd_limit")
    if rpd is not None:
        if rpd_l:
            parts.append(f"istek/gün {rpd}/{rpd_l}")
        else:
            parts.append(f"istek kalan {rpd}")
    tpm = q.get("tpm_kalan")
    if tpm is not None:
        parts.append(f"tpm kalan {tpm}")
    tpd_k = q.get("tpd_kalan")
    tpd_l = q.get("tpd_limit") or DEFAULT_TPD_LIMIT
    if tpd_k is not None:
        parts.append(f"token/gün ~{tpd_k}/{tpd_l}")
    else:
        used = q.get("tpd_kullanilan_tahmini") or q.get("tpd_kullanilan")
        if used is not None:
            parts.append(f"bugün ~{used}/{tpd_l} token (tahmini)")
    if q.get("son_429"):
        parts.append("⚠ kota uyarısı")
    return " · ".join(parts)


def _normalize_messages(
    prompt: str,
    messages: Optional[Sequence[ChatMessage]],
) -> List[ChatMessage]:
    if messages is not None:
        out: List[ChatMessage] = []
        for m in messages:
            role = str((m or {}).get("role") or "").strip()
            content = str((m or {}).get("content") or "").strip()
            if role in ("user", "assistant", "system") and content:
                out.append({"role": role, "content": content})
        if out:
            return out
    text = (prompt or "").strip()
    if not text:
        raise ValueError("call_chat: prompt veya messages gerekli")
    return [{"role": "user", "content": text}]


def _split_system(
    msgs: List[ChatMessage],
    system: Optional[str],
) -> tuple:
    """(system_text, user/assistant messages)."""
    sys_parts: List[str] = []
    if system and str(system).strip():
        sys_parts.append(str(system).strip())
    rest: List[ChatMessage] = []
    for m in msgs:
        if m["role"] == "system":
            sys_parts.append(m["content"])
        else:
            rest.append(m)
    return ("\n\n".join(sys_parts).strip(), rest)


def _call_groq(
    *,
    messages: List[ChatMessage],
    system: Optional[str],
    max_tokens: int,
    model: str,
    api_key: str,
    timeout: float,
) -> str:
    sys_text, rest = _split_system(messages, system)
    payload_msgs: List[ChatMessage] = []
    if sys_text:
        payload_msgs.append({"role": "system", "content": sys_text})
    payload_msgs.extend(rest)
    body = {
        "model": model,
        "messages": payload_msgs,
        "max_tokens": int(max_tokens),
        "temperature": 0.3,
    }
    # Cloudflare (1010) urllib varsayılan User-Agent'ı engeller — tarayıcı benzeri imza gerekli
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Makrofinans/1.0 (KararAsistan; +https://localhost)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
        hdrs = resp.headers
        raw = json.loads(resp.read().decode("utf-8"))
    usage = raw.get("usage") if isinstance(raw, dict) else None
    _update_quota_from_headers(
        hdrs,
        model=model,
        usage=usage if isinstance(usage, dict) else None,
    )
    choices = raw.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0].get("message") or {}).get("content") or ""
    return str(msg).strip()


def _call_anthropic(
    *,
    messages: List[ChatMessage],
    system: Optional[str],
    max_tokens: int,
    model: str,
    api_key: str,
) -> str:
    import anthropic

    sys_text, rest = _split_system(messages, system)
    # Anthropic: system ayrı; messages sadece user/assistant
    anthro_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in rest
        if m["role"] in ("user", "assistant")
    ]
    if not anthro_msgs:
        raise ValueError("Anthropic: en az bir user mesajı gerekli")

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: Dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens),
        "messages": anthro_msgs,
    }
    if sys_text:
        kwargs["system"] = sys_text
    response = client.messages.create(**kwargs)
    parts = getattr(response, "content", None) or []
    if not parts:
        return ""
    text = getattr(parts[0], "text", None) or str(parts[0])
    return (text or "").strip()


def call_chat(
    prompt: str = "",
    *,
    messages: Optional[Sequence[ChatMessage]] = None,
    system: Optional[str] = None,
    max_tokens: int = 400,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    _call_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """Senkron chat — rate limit + timeout.

    Geriye uyumlu: tek `prompt` veya `messages` (+ isteğe bağlı `system`).
    Test için `_call_fn(prompt_blob)->str`.
    HTTP 429 (Groq): bir kez LLM_MODEL_FALLBACK ile yeniden dener.
    """
    msgs = _normalize_messages(prompt, messages)
    sys_text, rest = _split_system(msgs, system)

    if _call_fn is not None:
        # Mock'lar tek string bekler — system + konuşmayı birleştir
        blob_parts = []
        if sys_text:
            blob_parts.append(f"[system]\n{sys_text}")
        for m in rest:
            blob_parts.append(f"[{m['role']}]\n{m['content']}")
        return (_call_fn("\n\n".join(blob_parts)) or "").strip()

    if not _rate_limit_ok():
        raise RuntimeError("rate_limit")

    p = (provider or resolve_provider()).lower()
    if p == "none":
        raise RuntimeError("LLM anahtarı yok (GROQ_API_KEY veya ANTHROPIC_API_KEY)")

    m = model or resolve_model(p)

    def _run(model_name: str) -> str:
        if p == "groq":
            key = api_key or groq_key()
            if not key:
                raise RuntimeError("GROQ_API_KEY yok")
            return _call_groq(
                messages=msgs,
                system=system,
                max_tokens=max_tokens,
                model=model_name,
                api_key=key,
                timeout=timeout,
            )
        if p == "anthropic":
            key = api_key or anthropic_key()
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY yok")
            return _call_anthropic(
                messages=msgs,
                system=system,
                max_tokens=max_tokens,
                model=model_name,
                api_key=key,
            )
        raise RuntimeError(f"Bilinmeyen LLM_PROVIDER: {p}")

    def _execute(model_name: str) -> str:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run, model_name)
            return fut.result(timeout=timeout)

    try:
        metin = _execute(m)
    except FutTimeout as e:
        raise TimeoutError(f"LLM timeout {timeout:.1f}s") from e
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        _log.warning("llm_client HTTP %s: %s", e.code, body)
        if int(e.code) == 429 and p == "groq":
            try:
                _update_quota_from_429_body(body, headers=getattr(e, "headers", None))
            except Exception:
                pass
            fb = resolve_fallback_model("groq")
            if fb and fb != m:
                _log.warning("llm_client 429 → yedek model %s", fb)
                try:
                    metin = _execute(fb)
                    _rate_limit_hit()
                    return (metin or "").strip()
                except FutTimeout as e2:
                    raise TimeoutError(f"LLM timeout {timeout:.1f}s") from e2
                except urllib.error.HTTPError as e2:
                    body2 = ""
                    try:
                        body2 = e2.read().decode("utf-8", errors="replace")[:280]
                    except Exception:
                        pass
                    _log.warning("llm_client fallback HTTP %s: %s", e2.code, body2)
                    try:
                        _update_quota_from_429_body(body2, headers=getattr(e2, "headers", None))
                    except Exception:
                        pass
                    if int(e2.code) == 429:
                        raise RuntimeError(
                            "LLM HTTP 429 daily_quota "
                            "(Groq günlük token kotası doldu — "
                            "birkaç saat / yarın tekrar veya LLM_MODEL_FALLBACK)"
                        ) from e2
                    raise RuntimeError(f"LLM HTTP {e2.code}") from e2
                except Exception:
                    raise
            raise RuntimeError(
                "LLM HTTP 429 daily_quota "
                "(Groq günlük token kotası doldu — birkaç saat / yarın tekrar)"
            ) from e
        raise RuntimeError(f"LLM HTTP {e.code}") from e

    _rate_limit_hit()
    return (metin or "").strip()
