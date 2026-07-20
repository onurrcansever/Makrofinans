# -*- coding: utf-8 -*-
"""Karar Asistanı AI yorumu — motor planını açıklar; rakam üretmez."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from llm_client import call_chat, provider_hint, provider_ready, resolve_model, resolve_provider

_log = logging.getLogger(__name__)

STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".karar_yorum_cache.json",
)

TTL_HOURS = 6
API_TIMEOUT_SEC = 8.0
FALLBACK = (
    "Yorum şu an üretilemedi. Plan tablosundaki rakamlar motordan gelmeye devam eder."
)
MAX_AL = 8
MAX_IZLE = 4


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        raw = str(s).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def yukle_cache() -> Dict[str, dict]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        _log.warning("karar_yorum cache okunamadı: %s", e)
        return {}


def kaydet_cache(cache: Dict[str, dict]) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".karar_yorum.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _cache_taze(entry: dict) -> bool:
    dt = _parse_ts(entry.get("guncelleme", ""))
    if dt is None:
        return False
    return (_now_utc() - dt) < timedelta(hours=TTL_HOURS)


def _safe_float(x: Any, nd: int = 1) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _plan_satirlari(plan) -> List[dict]:
    out = []
    for s in getattr(plan, "satirlar", None) or []:
        out.append({
            "sinif": getattr(s, "sinif", ""),
            "etiket": getattr(s, "etiket", ""),
            "tutar_tl": _safe_float(getattr(s, "tutar_tl", None), 0),
            "oran_pct": _safe_float(getattr(s, "oran_pct", None), 1),
            "mevcut_pct": _safe_float(getattr(s, "mevcut_pct", None), 1),
            "hedef_pct": _safe_float(getattr(s, "hedef_pct", None), 1),
            "arac": (getattr(s, "arac", "") or "")[:80],
            "gerekce": (getattr(s, "gerekce", "") or "")[:120],
        })
    return out


def _hisse_karar(h) -> str:
    from karar_lejant import _normalize_karar

    raw = (
        getattr(h, "signal_v2_decision", None)
        or getattr(h, "sinyal_v2_karar", None)
        or getattr(h, "karar", None)
        or getattr(h, "yonetici_aksiyon", None)
        or ""
    )
    return _normalize_karar(str(raw))


def _tarama_al_listesi(tarama, n: int = MAX_AL) -> List[dict]:
    hisseler = list(getattr(tarama, "hisseler", None) or [])
    adaylar = []
    for h in hisseler:
        norm = _hisse_karar(h)
        if norm not in ("AL", "GÜÇLÜ AL"):
            continue
        skor = getattr(h, "signal_v2_score", None)
        if skor is None:
            skor = getattr(h, "skor", None)
        alim = getattr(h, "signal_v2_al_price", None)
        if alim is None:
            alim = getattr(h, "yonetici_alim", None)
        adaylar.append({
            "sembol": getattr(h, "sembol", ""),
            "ad": (getattr(h, "ad", "") or "")[:40],
            "piyasa": getattr(h, "piyasa", "") or getattr(h, "varlik_turu", ""),
            "karar": norm,
            "skor": _safe_float(skor, 0),
            "1g_pct": _safe_float(getattr(h, "degisim_1g", None), 2),
            "alim_seviyesi": _safe_float(alim, 2),
            "neden": (getattr(h, "signal_v2_why", None) or getattr(h, "gerekce", "") or "")[:100],
        })
    adaylar.sort(key=lambda x: -(x.get("skor") or 0))
    return adaylar[:n]


def _tarama_izle_listesi(tarama, n: int = MAX_IZLE) -> List[dict]:
    """Skoru yüksek İZLE — takip için (şimdi alma değil)."""
    hisseler = list(getattr(tarama, "hisseler", None) or [])
    adaylar = []
    for h in hisseler:
        if _hisse_karar(h) != "İZLE":
            continue
        skor = getattr(h, "signal_v2_score", None)
        if skor is None:
            skor = getattr(h, "skor", None)
        adaylar.append({
            "sembol": getattr(h, "sembol", ""),
            "piyasa": getattr(h, "piyasa", ""),
            "skor": _safe_float(skor, 0),
        })
    adaylar.sort(key=lambda x: -(x.get("skor") or 0))
    return adaylar[:n]


def _endeks_ozeti(tarama) -> List[dict]:
    out = []
    for e in list(getattr(tarama, "endeksler", None) or []):
        out.append({
            "ad": getattr(e, "ad", ""),
            "sembol": getattr(e, "sembol", ""),
            "fiyat": _safe_float(getattr(e, "fiyat", None), 2),
            "1g_pct": _safe_float(getattr(e, "degisim_1g", None), 2),
            "1a_pct": _safe_float(getattr(e, "degisim_1ay", None), 2),
            "oneri": getattr(e, "aksiyon_etiket", None) or getattr(e, "aksiyon", "") or "—",
            "neden": (getattr(e, "gerekce", "") or "")[:90],
        })
    return out


def _fiili_sinif_pct(varlik_store, snap) -> Dict[str, float]:
    try:
        from nakit_danisman import _fiili_dagilim_tl

        portfoy = None
        if varlik_store is not None:
            portfoy = varlik_store.aktif() if hasattr(varlik_store, "aktif") else None
        dag = _fiili_dagilim_tl(portfoy, snap) if snap is not None else {}
        toplam = sum(float(v or 0) for v in dag.values()) or 1.0
        return {
            k: round(100.0 * float(v) / toplam, 1)
            for k, v in dag.items()
            if float(v or 0) > 0
        }
    except Exception:
        return {}


def karar_baglam_ozeti(
    plan,
    *,
    snap=None,
    tahsis=None,
    mevduat_ozet=None,
    tl_durum=None,
    tarama=None,
    danisman=None,
    varlik_store=None,
) -> Dict[str, Any]:
    """Token-dostu JSON özet — LLM prompt girdisi."""
    rejim = getattr(plan, "rejim_etiket", None) or ""
    if not rejim and tahsis is not None:
        rejim = getattr(getattr(tahsis, "rejim", None), "etiket", "") or ""

    makro: Dict[str, Any] = {}
    if snap is not None:
        v = getattr(snap, "veri", None)
        makro = {
            "eur_try": _safe_float(getattr(v, "eur_try", None), 2),
            "eur_try_1g_pct": _safe_float(getattr(snap, "eur_try_1g_degisim", None), 2),
            "cds_5y_bp": _safe_float(getattr(v, "cds_5y_bp", None), 0),
            "vix": _safe_float(getattr(snap, "vix", None), 1),
            "vix_1g_pct": _safe_float(getattr(snap, "vix_1g_degisim", None), 2),
            "bist100": _safe_float(getattr(snap, "bist100", None), 0),
            "bist100_1g_pct": _safe_float(getattr(snap, "bist100_1g_degisim", None), 2),
            "altin_usd": _safe_float(getattr(snap, "altin_usd_oz", None), 0),
            "altin_1g_pct": _safe_float(getattr(snap, "altin_1g_degisim", None), 2),
            "enflasyon_tr": _safe_float(getattr(snap, "enflasyon_tr_yillik", None), 1),
            "bist_vol_30g": _safe_float(getattr(snap, "bist_vol_30g", None), 1),
        }

    agirliklar: Dict[str, float] = {}
    if tahsis is not None:
        raw = getattr(tahsis, "agirliklar", None) or {}
        agirliklar = {
            str(k): round(100.0 * float(val), 1)
            for k, val in raw.items()
            if float(val or 0) > 0.005
        }

    mev: Dict[str, Any] = {}
    if mevduat_ozet is not None:
        mev = {
            "profil_vade": getattr(mevduat_ozet, "profil_vade", None),
            "net_pct": _safe_float(getattr(mevduat_ozet, "profil_vade_net", None), 1),
            "reel_pp": _safe_float(getattr(mevduat_ozet, "profil_vade_reel", None), 1),
        }

    tl: Dict[str, Any] = {}
    if tl_durum is not None:
        tl = {
            "baslik": getattr(tl_durum, "baslik", None),
            "pay_pct": _safe_float(getattr(tl_durum, "agirlik_pct", None), 1),
            "tavan_pct": _safe_float(getattr(tl_durum, "tavan_pct", None), 0),
        }

    dan: Dict[str, Any] = {}
    if danisman is not None:
        ry = (getattr(danisman, "rejim_yorumu", None) or "").strip()
        dan = {
            "rejim_yorumu": (ry[:220] + "…") if len(ry) > 220 else ry,
            "oncelik": list(getattr(danisman, "oncelik_sirasi", None) or [])[:3],
        }

    al_list = _tarama_al_listesi(tarama)
    return {
        "gorev": (
            "Kullanıcıya bugün ne yapabileceğini yönlendir: "
            "hangi piyasalar/hisseler önde, yeni para planı nasıl okunmalı, ne beklenmeli."
        ),
        "plan": {
            "girilen_tutar": _safe_float(getattr(plan, "girilen_tutar", None), 0),
            "para_birimi": getattr(plan, "para_birimi", ""),
            "tutar_tl": _safe_float(getattr(plan, "tutar_tl", None), 0),
            "mevcut_toplam_tl": _safe_float(getattr(plan, "mevcut_toplam_tl", None), 0),
            "yeni_toplam_tl": _safe_float(getattr(plan, "yeni_toplam_tl", None), 0),
            "rejim": rejim,
            "satirlar": _plan_satirlari(plan),
            "notlar": list(getattr(plan, "notlar", None) or [])[:4],
        },
        "makro": makro,
        "tahsis_agirlik_pct": agirliklar,
        "mevduat": mev,
        "tl_karar": tl,
        "endeksler": _endeks_ozeti(tarama),
        "al_adaylari": al_list,
        "al_adet": len(al_list),
        "izle_takip": _tarama_izle_listesi(tarama),
        "danisman": dan,
        "fiili_sinif_pct": _fiili_sinif_pct(varlik_store, snap),
    }


def baglam_cache_anahtar(baglam: Dict[str, Any]) -> str:
    blob = json.dumps(baglam, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _build_prompt(baglam: Dict[str, Any]) -> str:
    veri = json.dumps(baglam, ensure_ascii=False, indent=2)
    return f"""Sen bir portföy karar destek asistanısın. Kullanıcı yeni para / vade planına
bakıyor ve **genel sistemi** anlayıp ne yapacağını bilmek istiyor.

Aşağıdaki JSON yazılımın motorlarından gelir (tahsis, makro, endeks, AL listesi,
nakit planı). Rakamları yeniden hesaplama; yüzdeleri değiştirme.

Yanıtı Türkçe, net, yönlendirici yaz — şu yapıda (başlıklar kullan):

1) **Piyasa / rejim** — VIX, BIST, CDS, altın, EUR/TRY ve rejim etiketini 2–3 cümlede özetle; risk-on mu temkin mi.
2) **Yeni para planı** — tablodaki dağılımı (mevduat / altın / hisse dilimleri) neden böyle okumalı; TL tavanı varsa belirt.
3) **Hisse & ETF — ne yapmalı** — `al_adaylari` varsa sembol + piyasa ile öncelik sırası ver; alım seviyesi varsa söyle. AL yoksa açıkça "şimdi yeni hisse ekleme; İZLE takip" de. `izle_takip` yalnızca takip.
4) **Endeksler** — BIST / S&P / NASDAQ önerisini (Artır/Koru/Bekle/Azalt) kısaca yorumla.
5) **Bugün için net aksiyon** — 3 madde: (a) paranın çoğu nereye, (b) hisse tarafında ne, (c) neyi beklemeli.

Kurallar:
- "Kesinlikle al/sat" deme; "değerlendirilebilir / öncelikli aday / şimdilik bekle" dili kullan.
- Sadece VERİ'deki sembolleri say; uydurma ticker ekleme.
- Yasal uyarı ekleme (ayrıca gösterilecek).
- Toplam ~12–18 cümle / maddeli; okunaklı olsun.

VERİ:
{veri}
"""


def karar_ai_yorum(
    baglam: Dict[str, Any],
    *,
    force: bool = False,
    timeout: float = API_TIMEOUT_SEC,
    _call_fn=None,
) -> Tuple[str, Dict[str, Any]]:
    """(metin, meta). meta: cache_hit, model, provider, hata, guncelleme."""
    key = baglam_cache_anahtar(baglam)
    provider = resolve_provider()
    model = resolve_model(provider)
    meta: Dict[str, Any] = {
        "cache_hit": False,
        "guncelleme": _now_utc().isoformat(),
        "model": model,
        "provider": provider,
        "anahtar": key,
        "hint": provider_hint(),
    }

    cache = yukle_cache()
    if not force:
        ent = cache.get(key)
        if ent and _cache_taze(ent) and ent.get("metin"):
            meta["cache_hit"] = True
            meta["guncelleme"] = ent.get("guncelleme") or meta["guncelleme"]
            meta["model"] = ent.get("model") or model
            meta["provider"] = ent.get("provider") or provider
            return str(ent["metin"]), meta

    if not provider_ready() and _call_fn is None:
        meta["hata"] = "no_key"
        return (
            FALLBACK + " " + provider_hint(),
            meta,
        )

    prompt = _build_prompt(baglam)
    # Plan tutarının prompt'ta olduğundan emin (test)
    try:
        tutar = (baglam.get("plan") or {}).get("tutar_tl")
        if tutar is not None and str(int(tutar)) not in prompt.replace(",", ""):
            prompt += f"\n\nDağıtılacak tutar (TL): {tutar}"
    except Exception:
        pass

    try:
        metin = call_chat(
            prompt,
            max_tokens=700,
            timeout=timeout,
            _call_fn=_call_fn,
        )
    except Exception as e:
        _log.warning("karar_ai_yorum: %s", e)
        meta["hata"] = str(e)
        from llm_shared import hata_metni

        return hata_metni(e, fallback=FALLBACK), meta

    metin = (metin or "").strip() or FALLBACK
    cache[key] = {
        "metin": metin,
        "guncelleme": meta["guncelleme"],
        "model": model,
        "provider": provider,
    }
    try:
        kaydet_cache(cache)
    except Exception as e:
        _log.warning("karar_yorum cache yazılamadı: %s", e)
    return metin, meta


def format_karar_yorum_markdown(metin: str, meta: Optional[dict] = None) -> str:
    meta = meta or {}
    src = meta.get("hint") or meta.get("provider") or "AI"
    hit = " · cache" if meta.get("cache_hit") else ""
    return (
        f"**AI yorum** ({src}{hit})\n\n"
        f"{metin}\n\n"
        "_Rakamlar motordan · yatırım tavsiyesi değildir._"
    )
