# -*- coding: utf-8 -*-
"""
Aşama 2C — Portföy genel yorumu.
Özet metrikler Python'da; LLM yalnızca özet dict görür (pozisyon detayı yok).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_log = logging.getLogger(__name__)

STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".portfoy_yorum_cache.json",
)

TTL_HOURS = 6
API_TIMEOUT_SEC = 5.0
MAX_PER_MINUTE = 10
FALLBACK = "Yorum şu an mevcut değil"
MODEL = "claude-sonnet-4-6"
KONSANTRASYON_ESIK = 30.0

# Sembol kökü → sektör (normalize: nokta sonrası atılır)
_SEKTOR_MAP: Dict[str, str] = {}
for _sym in ("GARAN", "AKBNK", "YKBNK", "HALKB", "VAKBN", "ISCTR"):
    _SEKTOR_MAP[_sym] = "BIST banka"
for _sym in ("EREGL", "KRDMD", "ARCLK", "TOASO", "FROTO"):
    _SEKTOR_MAP[_sym] = "BIST sanayi"
for _sym in (
    "MSFT", "AAPL", "GOOGL", "GOOG", "META", "NVDA", "AMD", "CSCO",
    "AMAT", "MU", "INTU", "ORCL", "NFLX", "AVGO", "QCOM", "TXN", "ADBE",
):
    _SEKTOR_MAP[_sym] = "ABD teknoloji"
for _sym in ("UNH", "JNJ", "LLY", "MRK", "ABBV", "GILD", "TMO"):
    _SEKTOR_MAP[_sym] = "ABD sağlık"
for _sym in ("EQQQ", "CSPX", "VUAA", "VUSA", "IWDA", "SWRD", "EIMI", "VHYL"):
    _SEKTOR_MAP[_sym] = "ETF"

_rate_ts: List[float] = []


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


def sembol_kok(sembol: str) -> str:
    s = (sembol or "").strip().upper()
    if not s:
        return ""
    return s.split(".")[0].split(":")[-1]


def sektor_bul(sembol: str, *, tur: str = "") -> str:
    if (tur or "").lower() == "etf":
        kok = sembol_kok(sembol)
        return _SEKTOR_MAP.get(kok, "ETF")
    kok = sembol_kok(sembol)
    if kok in _SEKTOR_MAP:
        return _SEKTOR_MAP[kok]
    if (tur or "").lower() in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return "Nakit / mevduat"
    if (tur or "").lower() in ("altin", "gumus"):
        return "Kıymetli maden"
    if (tur or "").lower() == "kripto":
        return "Kripto"
    if (tur or "").lower() == "tefas":
        return "TEFAS"
    return "Diğer"


def yukle_cache() -> Dict[str, dict]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        _log.warning("portfoy_yorum cache okunamadı: %s", e)
        return {}


def kaydet_cache(cache: Dict[str, dict]) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".portfoy_yorum.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _cache_taze(entry: dict, *, now: Optional[datetime] = None) -> bool:
    ts = _parse_ts(entry.get("guncelleme", ""))
    if ts is None:
        return False
    ref = now or _now_utc()
    return (ref - ts) < timedelta(hours=TTL_HOURS)


def cache_anahtar(pozisyon_listesi: Sequence[Any], *, gun: Optional[str] = None) -> str:
    """hash(pozisyon özeti + tarih)."""
    gun = gun or date.today().isoformat()
    parcalar: List[str] = []
    for p in pozisyon_listesi:
        if isinstance(p, dict):
            parcalar.append(
                f"{p.get('sembol','')}|{p.get('miktar',0)}|{p.get('maliyet',0)}|{p.get('kar_zarar_pct',0)}"
            )
        else:
            parcalar.append(
                f"{getattr(p, 'sembol', '')}|{getattr(p, 'miktar', 0)}|"
                f"{getattr(p, 'maliyet', 0)}|{getattr(p, 'kar_zarar_pct', getattr(p, 'kz_pct', 0))}"
            )
    raw = gun + "\n" + "\n".join(sorted(parcalar))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


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


def _karar_normalize(karar: str) -> str:
    k = (karar or "").strip().upper().replace("İ", "I")
    if "GUCLU" in k.replace("Ü", "U").replace("Ğ", "G") or "GÜÇLÜ" in (karar or "").upper():
        return "AL"
    if "AZALT" in k:
        return "AZALT"
    if "IZLE" in k or "İZLE" in (karar or "").upper():
        return "İZLE"
    if "BEKLE" in k:
        return "BEKLE"
    if k == "AL" or (karar or "").strip().upper() == "AL":
        return "AL"
    return (karar or "—").strip() or "—"


def _tarama_index(tarama) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if tarama is None:
        return out
    hisseler = getattr(tarama, "hisseler", None) or getattr(tarama, "sonuclar", None) or []
    if isinstance(tarama, (list, tuple)):
        hisseler = tarama
    for h in hisseler:
        sym = getattr(h, "sembol", None) or (h.get("sembol") if isinstance(h, dict) else None)
        if not sym:
            continue
        out[sembol_kok(sym)] = h
        out[str(sym).strip().upper()] = h
    return out


def _hisse_alan(h, *names, default=None):
    for n in names:
        if h is None:
            break
        if isinstance(h, dict) and n in h:
            return h[n]
        if hasattr(h, n):
            v = getattr(h, n)
            if v is not None and v != "":
                return v
    return default


def sektor_agirliklari(
    satirlar: Sequence[dict],
) -> Tuple[Dict[str, float], Optional[str], bool]:
    """
    satirlar: {sektor, agirlik} veya {sembol, tur, deger}.
    Dönüş: {sektor: pct}, en_buyuk etiketi, konsantrasyon_uyari.
    """
    toplam = 0.0
    bucket: Dict[str, float] = {}
    for s in satirlar:
        if "agirlik" in s and "sektor" in s and "deger" not in s:
            w = float(s.get("agirlik") or 0)
            sk = s["sektor"]
        else:
            w = float(s.get("deger") or s.get("agirlik") or 0)
            sk = s.get("sektor") or sektor_bul(s.get("sembol", ""), tur=s.get("tur", ""))
        if w <= 0:
            continue
        bucket[sk] = bucket.get(sk, 0.0) + w
        toplam += w
    if toplam <= 0:
        return {}, None, False
    pct = {k: round(v / toplam * 100.0, 1) for k, v in bucket.items()}
    en_ad, en_pct = max(pct.items(), key=lambda kv: kv[1])
    en_buyuk = f"{en_ad} %{en_pct:g}"
    uyari = en_pct >= KONSANTRASYON_ESIK
    return pct, en_buyuk, uyari


def portfoy_ozet_hesapla(
    pozisyonlar: Sequence[Any],
    tarama=None,
    *,
    temel_cache: Optional[Dict[str, dict]] = None,
    deger_pozisyonlar: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """
    Python özet metrikleri (LLM'e gitmeden önce).

    pozisyonlar: VarlikPozisyon veya dict (sembol, miktar, maliyet, tur).
    deger_pozisyonlar: PozisyonDeger listesi (kar_zarar_pct, guncel_deger) — varsa tercih edilir.
    """
    idx = _tarama_index(tarama)
    temel_cache = temel_cache or {}

    rows: List[dict] = []
    if deger_pozisyonlar:
        for pd_ in deger_pozisyonlar:
            p = getattr(pd_, "pozisyon", pd_)
            rows.append({
                "sembol": getattr(p, "sembol", "") or "",
                "tur": getattr(p, "tur", "") or "",
                "miktar": float(getattr(p, "miktar", 0) or 0),
                "maliyet": float(getattr(pd_, "maliyet_deger", None) or getattr(p, "maliyet", 0) or 0),
                "kar_zarar_pct": float(getattr(pd_, "kar_zarar_pct", 0) or 0),
                "deger": float(getattr(pd_, "guncel_deger", 0) or 0),
            })
    else:
        for p in pozisyonlar:
            if isinstance(p, dict):
                rows.append({
                    "sembol": p.get("sembol", "") or "",
                    "tur": p.get("tur", "") or "",
                    "miktar": float(p.get("miktar") or 0),
                    "maliyet": float(p.get("maliyet") or 0),
                    "kar_zarar_pct": float(p.get("kar_zarar_pct") or 0),
                    "deger": float(p.get("deger") or p.get("guncel_deger") or p.get("maliyet") or 0),
                })
            else:
                rows.append({
                    "sembol": getattr(p, "sembol", "") or "",
                    "tur": getattr(p, "tur", "") or "",
                    "miktar": float(getattr(p, "miktar", 0) or 0),
                    "maliyet": float(getattr(p, "maliyet", 0) or 0),
                    "kar_zarar_pct": float(getattr(p, "kar_zarar_pct", 0) or 0),
                    "deger": float(getattr(p, "deger", 0) or getattr(p, "maliyet", 0) or 0),
                })

    # Ağırlık yoksa eşit dağıt
    toplam_deger = sum(max(0.0, r["deger"]) for r in rows)
    if toplam_deger <= 0 and rows:
        for r in rows:
            r["deger"] = 1.0
        toplam_deger = float(len(rows))

    sektor_satir = [
        {"sembol": r["sembol"], "tur": r["tur"], "deger": r["deger"]}
        for r in rows
    ]
    sektor_pct, en_buyuk, kons_uyari = sektor_agirliklari(sektor_satir)

    karar_say: Dict[str, int] = {"AL": 0, "İZLE": 0, "BEKLE": 0, "AZALT": 0, "—": 0}
    azalt_agirlik = 0.0
    skor_w = 0.0
    skor_sum = 0.0
    temel_analist: Dict[str, int] = {}

    for r in rows:
        kok = sembol_kok(r["sembol"])
        h = idx.get(kok) or idx.get((r["sembol"] or "").upper())
        karar_raw = _hisse_alan(h, "signal_v2_decision", "karar", default="—")
        karar = _karar_normalize(str(karar_raw))
        if karar not in karar_say:
            karar_say[karar] = 0
        karar_say[karar] = karar_say.get(karar, 0) + 1
        w = (r["deger"] / toplam_deger * 100.0) if toplam_deger > 0 else 0.0
        if karar == "AZALT":
            azalt_agirlik += w
        skor = _hisse_alan(h, "signal_v2_score", "skor", default=None)
        if skor is not None:
            try:
                skor_f = float(skor)
                skor_sum += skor_f * w
                skor_w += w
            except (TypeError, ValueError):
                pass
        # Temel (sembol bazlı; LLM'e sembol gitmez — yalnızca sayaç)
        t = temel_cache.get(r["sembol"]) or temel_cache.get(kok) or {}
        if not t and r["sembol"]:
            try:
                from temel_veri import get_temel
                t = get_temel(r["sembol"]) or {}
            except Exception:
                t = {}
        ak = t.get("recommendationKey") or t.get("analist")
        if ak:
            temel_analist[str(ak)] = temel_analist.get(str(ak), 0) + 1

    ort_skor = int(round(skor_sum / skor_w)) if skor_w > 0 else 0

    # Portföy K/Z: ağırlıklı ortalama kar_zarar_pct (değer ağırlıklı)
    kz_sum = 0.0
    mal_sum = 0.0
    for r in rows:
        m = r["maliyet"]
        if m > 0:
            mal_sum += m
            kz_sum += m * (1.0 + r["kar_zarar_pct"] / 100.0)
    if mal_sum > 0:
        portfoy_kz = (kz_sum / mal_sum - 1.0) * 100.0
    else:
        portfoy_kz = 0.0

    sirali = sorted(rows, key=lambda x: x["kar_zarar_pct"])
    en_zararli = [
        f"{sembol_kok(r['sembol']) or r['tur']} {r['kar_zarar_pct']:+.0f}%"
        for r in sirali[:3]
        if r["sembol"] or r["tur"]
    ]
    en_kazanli = [
        f"{sembol_kok(r['sembol']) or r['tur']} {r['kar_zarar_pct']:+.0f}%"
        for r in reversed(sirali[-3:])
        if r["sembol"] or r["tur"]
    ]

    return {
        "toplam_pozisyon": len(rows),
        "azalt_agirlik_pct": round(azalt_agirlik, 1),
        "ortalama_skor": ort_skor,
        "en_buyuk_sektor": en_buyuk or "—",
        "konsantrasyon_uyari": bool(kons_uyari),
        "portfoy_kz_pct": round(portfoy_kz, 1),
        "en_zararli": en_zararli,
        "en_kazanli": en_kazanli,
        # UI / debug (LLM prompt'a sembolsüz gider)
        "sektor_dagilim": sektor_pct,
        "karar_sayilari": {k: v for k, v in karar_say.items() if v},
        "analist_ozet": (
            ", ".join(f"{v}× {k}" for k, v in sorted(temel_analist.items()))
            if temel_analist else ""
        ),
    }


_TICKER_RE = re.compile(
    r"\b(?:GARAN|AKBNK|YKBNK|HALKB|VAKBN|ISCTR|EREGL|KRDMD|ARCLK|TOASO|FROTO|"
    r"MSFT|AAPL|GOOGL?|META|NVDA|AMD|CSCO|AMAT|MU|INTU|ORCL|NFLX|AVGO|QCOM|"
    r"UNH|JNJ|LLY|MRK|ABBV|GILD|TMO|EQQQ|CSPX|VUAA|VUSA)\b",
    re.I,
)


def _anon_pct_liste(items: Iterable[str]) -> List[str]:
    """'INTU -62%' → '-62%' — LLM prompt'unda sembol yok."""
    out = []
    for it in items or []:
        s = str(it)
        m = re.search(r"([+-]?\d+(?:\.\d+)?\s*%)", s)
        out.append(m.group(1).replace(" ", "") if m else s)
    return out


def _build_prompt(ozet: dict) -> str:
    """Yalnızca özet metrikler; sembol adları ve pozisyon detayı yok."""
    zarar = ", ".join(_anon_pct_liste(ozet.get("en_zararli") or [])) or "—"
    kazanc = ", ".join(_anon_pct_liste(ozet.get("en_kazanli") or [])) or "—"
    return f"""Portföy özeti:
- {ozet.get('toplam_pozisyon', 0)} pozisyon, ağırlıklı ortalama sinyal skoru {ozet.get('ortalama_skor', 0)}/100
- AZALT sinyalli pozisyonlar: portföyün %{ozet.get('azalt_agirlik_pct', 0)}'i
- En büyük konsantrasyon: {ozet.get('en_buyuk_sektor', '—')}
- Portföy K/Z: {float(ozet.get('portfoy_kz_pct') or 0):+.1f}%
- En zararlı (yüzdeler): {zarar}
- En kazançlı (yüzdeler): {kazanc}

2-3 cümleyle portföyün genel durumunu değerlendir.
KURALLAR:
- Sadece verilen verilere dayan
- "Al/sat" tavsiyesi verme
- "Şunu sat, bunu al" deme
- Konsantrasyon varsa belirt
- Türkçe, sade dil
- Sembol / hisse adı kullanma
"""


def prompt_sembol_icerir_mi(prompt: str) -> bool:
    """Test yardımcısı: bilinen ticker'lar prompt'ta var mı?"""
    return bool(_TICKER_RE.search(prompt or ""))


def _call_anthropic(prompt: str, *, api_key: Optional[str] = None) -> str:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    if not key or key.startswith("your_key"):
        raise RuntimeError("ANTHROPIC_API_KEY yok")
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=220,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(response, "content", None) or []
    if not parts:
        return FALLBACK
    text = getattr(parts[0], "text", None) or str(parts[0])
    return (text or "").strip() or FALLBACK


def portfoy_genel_yorum(
    ozet: dict,
    *,
    pozisyon_listesi: Optional[Sequence[Any]] = None,
    force: bool = False,
    timeout: float = API_TIMEOUT_SEC,
    api_key: Optional[str] = None,
    _call_fn=None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Dönüş: (metin, meta). Cache anahtarı = hash(pozisyon_listesi + tarih).
    pozisyon_listesi verilmezse ozet alanlarından türetilir.
    """
    if pozisyon_listesi is None:
        pozisyon_listesi = [
            {"sembol": x.split()[0], "miktar": 1, "maliyet": 1,
             "kar_zarar_pct": 0}
            for x in (ozet.get("en_zararli") or []) + (ozet.get("en_kazanli") or [])
        ]
        # Stabil anahtar için ozet imzası
        pozisyon_listesi = [{"sembol": "_ozet_", "miktar": ozet.get("toplam_pozisyon", 0),
                             "maliyet": ozet.get("ortalama_skor", 0),
                             "kar_zarar_pct": ozet.get("portfoy_kz_pct", 0),
                             "extra": json.dumps(ozet, sort_keys=True, ensure_ascii=False)}]

    key = cache_anahtar(pozisyon_listesi)
    # Ozet değişince de yeni anahtar — hash'e ozet özeti ekle
    key = hashlib.sha256(
        (key + "|" + json.dumps({
            k: ozet.get(k) for k in (
                "toplam_pozisyon", "azalt_agirlik_pct", "ortalama_skor",
                "en_buyuk_sektor", "portfoy_kz_pct", "en_zararli", "en_kazanli",
            )
        }, ensure_ascii=False, sort_keys=True)).encode()
    ).hexdigest()[:32]

    cache = yukle_cache()
    meta: Dict[str, Any] = {
        "cache_hit": False,
        "guncelleme": _now_utc().isoformat(),
        "model": MODEL,
        "anahtar": key,
    }

    if not force:
        ent = cache.get(key)
        if ent and _cache_taze(ent) and ent.get("metin"):
            meta["cache_hit"] = True
            meta["guncelleme"] = ent.get("guncelleme") or meta["guncelleme"]
            return str(ent["metin"]), meta

    if not _rate_limit_ok():
        meta["hata"] = "rate_limit"
        return FALLBACK, meta

    prompt = _build_prompt(ozet)
    if prompt_sembol_icerir_mi(prompt):
        _log.warning("portfoy_yorum: prompt'ta sembol sızıntısı — anonimize tekrar")
        # Güvenlik ağı: ticker'ları sil
        prompt = _TICKER_RE.sub("[pozisyon]", prompt)

    call = _call_fn or _call_anthropic

    def _run():
        if _call_fn is not None:
            return call(prompt)
        return call(prompt, api_key=api_key)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run)
            metin = fut.result(timeout=timeout)
    except FutTimeout:
        _log.warning("portfoy_yorum: timeout %.1fs", timeout)
        meta["hata"] = "timeout"
        return FALLBACK, meta
    except Exception as e:
        _log.warning("portfoy_yorum: %s", e)
        meta["hata"] = str(e)
        return FALLBACK, meta

    _rate_limit_hit()
    metin = (metin or "").strip() or FALLBACK
    cache[key] = {
        "metin": metin,
        "guncelleme": _now_utc().isoformat(),
        "model": MODEL,
        "ozet": {
            k: ozet.get(k) for k in (
                "toplam_pozisyon", "azalt_agirlik_pct", "ortalama_skor",
                "en_buyuk_sektor", "portfoy_kz_pct",
            )
        },
    }
    try:
        kaydet_cache(cache)
    except Exception as e:
        _log.warning("portfoy_yorum cache yazılamadı: %s", e)
    meta["cache_hit"] = False
    return metin, meta


def format_portfoy_yorum_markdown(metin: str, meta: Optional[dict] = None) -> str:
    meta = meta or {}
    gun = meta.get("guncelleme") or _now_utc().isoformat()
    try:
        dt = _parse_ts(str(gun)) or _now_utc()
        aylar = (
            "Oca", "Şub", "Mar", "Nis", "May", "Haz",
            "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
        )
        local = dt.astimezone() if dt.tzinfo else dt
        etiket = f"{local.day} {aylar[local.month - 1]} {local.year}"
        # "6s önce" benzeri
        age = _now_utc() - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
        secs = int(age.total_seconds())
        if secs < 90:
            age_s = f"{max(0, secs)}s önce"
        elif secs < 3600:
            age_s = f"{secs // 60}dk önce"
        else:
            age_s = etiket
    except Exception:
        age_s = str(gun)[:10]
    return f"{metin}\n\n[Claude · {age_s}]"


def format_durum_gunu(gun: Optional[str] = None) -> str:
    d = datetime.strptime((gun or date.today().isoformat())[:10], "%Y-%m-%d")
    aylar = (
        "Oca", "Şub", "Mar", "Nis", "May", "Haz",
        "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
    )
    return f"{d.day} {aylar[d.month - 1]} {d.year}"
