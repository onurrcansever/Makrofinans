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
API_TIMEOUT_SEC = 10.0
MAX_PER_MINUTE = 10
FALLBACK = "Açıklama şu an mevcut değil"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 700

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


def _format_tech_snapshot(tech_snapshot: Optional[Any]) -> str:
    if tech_snapshot is None:
        return ""
    if isinstance(tech_snapshot, dict):
        rows = tech_snapshot.get("rows") or []
        lines = ["Teknik özet (günlük — yalnızca verilen göstergeler):"]
        for row in rows:
            if len(row) >= 3:
                lines.append(f"- {row[0]}: {row[1]} — {row[2]}")
        for key, label in (
            ("kisa_okuma", "Kısa vade"),
            ("uzun_okuma", "Orta/uzun vade"),
            ("ozet", "Özet"),
            ("aksiyon_okuma", "Birleşik aksiyon okuma"),
        ):
            if tech_snapshot.get(key):
                lines.append(f"- {label}: {tech_snapshot[key]}")
        if tech_snapshot.get("al_seviyesi") is not None:
            lines.append(
                f"- Alım seviyesi (motor): {tech_snapshot['al_seviyesi']} "
                f"(spot_near={tech_snapshot.get('spot_near')}; "
                f"yöntem={tech_snapshot.get('al_method') or '—'})"
            )
        if "ichimoku_buy_zone" in tech_snapshot or tech_snapshot.get("ichimoku_note"):
            bz = tech_snapshot.get("ichimoku_buy_zone")
            if bz is True:
                bz_s = "alım bölgesi AÇIK"
            elif bz is False:
                bz_s = "alım bölgesi KAPALI — bekle"
            else:
                bz_s = "veri yok"
            lines.append(
                f"- Ichimoku: {bz_s} · not: {tech_snapshot.get('ichimoku_note') or '—'}"
            )
        lines.append(
            "- Not: MACD, Stokastik, Williams, haftalık bar yok — uydurma."
        )
        return "\n".join(lines)
    prompt_block = getattr(tech_snapshot, "prompt_block", None)
    if callable(prompt_block):
        return str(prompt_block())
    return ""


def _build_prompt(
    sembol: str,
    karar: str,
    skor: int,
    faktorler: dict,
    temel: dict,
    fiyat_eur: float,
    getiri_1y: float,
    rejim: str,
    *,
    tech_snapshot: Optional[Any] = None,
) -> str:
    tech_block = _format_tech_snapshot(tech_snapshot)
    tech_section = f"\n{tech_block}\n" if tech_block else ""
    return f"""Sen sabırlı bir yatırım öğretmenisin / mentorsun. Aşağıdaki VERİYE dayanarak
{sembol} için detaylı Türkçe bir anlatım yaz (yaklaşık 10–14 cümle).
Amaç: karşı tarafa **ana kararı tüm gerekçeleriyle öğretmek** — emir vermek değil,
neden böyle okuduğumuzu açıklamak. Ton: sade, didaktik, doğal paragraf;
madde numarası veya sert yasak listesi gibi yazma.

Motor «Şimdi ne yap?» kararı:
- Karar: {karar} (skor: {skor}/100)
- Trend: {_faktor_al(faktorler, 'trend')}/100
- Momentum: {_faktor_al(faktorler, 'mean_reversion', 'mean_rev')}/100
- Volatilite: {_faktor_al(faktorler, 'volatility', 'vol')}/100
- Göreli güç: {_faktor_al(faktorler, 'relative_strength', 'rel')}/100
- Likidite: {_faktor_al(faktorler, 'liquidity', 'lik')}/100
- Rejim: {rejim}
{tech_section}
Temel / analist:
{_format_temel(temel)}

Fiyat: {fiyat_eur:.2f} EUR | 1Y getiri: {getiri_1y:+.1f}%

ANLATIM AKIŞI (esnek paragraflar; her katmanda «neden önemli»yi söyle):
1) Kısa vade: RSI ve fiyatın SMA20’ye göre konumu (üstünde/altında — net dil)
2) Orta/uzun: fiyat vs SMA50/SMA200 — destek mi baskı mı, kısa vade ile çelişiyor mu
3) Temel/analist varsa: teknikle nasıl birlikte okunur (yoksa «veride yok»)
4) Motor kararı ({karar}): skor eşiğinin geçilmesi ne demek; bunun «hemen al» emri
   olmadığını öğret
5) Ichimoku ve alım seviyesi: yeşil ışık mı, fren mi — motor AL iken teyit yoksa
   bunu bilerek açıkla («listede AL görünmesi ile şu an alıma geçmek aynı şey değil; sebep …»)
6) Ana karar özeti: bu yüzden bekle / seviyeden değerlendir / kademeli — bir kez,
   gerekçeleri toplayarak
7) Kısa risk / temkin

DİL REHBERİ:
- «fiyat SMA20’nin altında/üstünde» de; karışık «SMA20 fiyatın altında» cümleleri kurma
- Veride olmayan gösterge uydurma (MACD, Stokastik, Williams, haftalık, SMA5/10/100)
- Haber veya anlamsız bağlaç uydurma
- Aynı sonucu iki kez tekrarlama; bir özet yeter
- "Kesinlikle al/sat" deme — olasılık / izleme dili
- Yasal uyarı ekleme (ayrıca gösterilecek)
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
    tech_snapshot: Optional[Any] = None,
    force: bool = False,
    timeout: float = API_TIMEOUT_SEC,
    api_key: Optional[str] = None,
    _call_fn=None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Dönüş: (metin, meta) — meta: cache_hit, guncelleme, model, hata.
    _call_fn: test mock (prompt -> str).
    tech_snapshot: TechSnapshot veya dict (skora girmez).
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
        tech_snapshot=tech_snapshot,
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
