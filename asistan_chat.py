# -*- coding: utf-8 -*-
"""Global Asistan sohbeti — yazılım verisini bağlam alan çok turlu AI."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from llm_client import call_chat, provider_hint, provider_ready, resolve_model, resolve_provider

_log = logging.getLogger(__name__)

API_TIMEOUT_SEC = 12.0
MAX_AL = 8
MAX_IZLE = 4
MAX_TEFAS = 5
MAX_POZISYON = 8
MAX_HISTORY_TURNS = 8  # user+assistant çiftleri
VIX_TEMKIN_ESIK = 25.0
FALLBACK = (
    "Yanıt şu an üretilemedi. Makro, tahsis ve tarama sayfalarındaki "
    "rakamlar motordan gelmeye devam eder."
)
MSG_429 = (
    "Groq günlük token kotası doldu (ücretsiz limit). "
    "Birkaç saat veya yarın tekrar deneyin; "
    "veya `.env` içinde `LLM_MODEL=llama-3.1-8b-instant` kullanın."
)

# Ticker benzeri tokenlar (AAPL, THYAO.IS, GC=F, BRK.B)
_TICKER_RE = re.compile(
    r"\b([A-Z]{2,10}(?:[.=][A-Z0-9]{1,4})?)\b"
)
# Grounding dışı bırakılacak yaygın kısaltmalar / para birimleri
_TICKER_STOP = frozenset({
    "AL", "TL", "USD", "EUR", "GBP", "CHF", "RON", "VIX", "CDS", "ETF",
    "BIST", "AI", "API", "PDF", "OK", "PP", "NA", "NATO", "ABD", "TR",
    "YK", "TEFAS", "RSI", "SMA", "EMA", "PE", "PB", "ROE", "LLM",
})

HAZIR_SORULAR = (
    "Bugün ne yapayım?",
    "AL adaylarım neler?",
    "TL mi altın mı?",
    "Portföyüm rejimle uyumlu mu?",
)
PLAN_SORUSU = "Son nakit planımı açıkla"


def _safe_float(x: Any, nd: int = 1) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _makro(snap) -> Dict[str, Any]:
    if snap is None:
        return {}
    v = getattr(snap, "veri", None)
    return {
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


def _tahsis_pct(tahsis) -> Dict[str, float]:
    if tahsis is None:
        return {}
    raw = getattr(tahsis, "agirliklar", None) or {}
    return {
        str(k): round(100.0 * float(val), 1)
        for k, val in raw.items()
        if float(val or 0) > 0.005
    }


def _rejim_etiket(tahsis, plan=None) -> str:
    if plan is not None:
        r = getattr(plan, "rejim_etiket", None) or ""
        if r:
            return str(r)
    if tahsis is None:
        return ""
    return str(getattr(getattr(tahsis, "rejim", None), "etiket", "") or "")


def _rejim_kod(tahsis) -> str:
    if tahsis is None:
        return ""
    return str(getattr(getattr(tahsis, "rejim", None), "rejim", "") or "").upper()


def _mevduat(mevduat_ozet) -> Dict[str, Any]:
    if mevduat_ozet is None:
        return {}
    return {
        "profil_vade": getattr(mevduat_ozet, "profil_vade", None),
        "net_pct": _safe_float(getattr(mevduat_ozet, "profil_vade_net", None), 1),
        "reel_pp": _safe_float(getattr(mevduat_ozet, "profil_vade_reel", None), 1),
        "ozet": (getattr(mevduat_ozet, "ozet", None) or "")[:160],
    }


def _tl_karar(tl_durum) -> Dict[str, Any]:
    if tl_durum is None:
        return {}
    return {
        "baslik": getattr(tl_durum, "baslik", None),
        "pay_pct": _safe_float(getattr(tl_durum, "agirlik_pct", None), 1),
        "tavan_pct": _safe_float(getattr(tl_durum, "tavan_pct", None), 0),
    }


def _danisman_ozet(danisman) -> Dict[str, Any]:
    if danisman is None:
        return {}
    ry = (getattr(danisman, "rejim_yorumu", None) or "").strip()
    genel = (getattr(danisman, "genel_ozet", None) or "").strip()
    return {
        "rejim_yorumu": (ry[:180] + "…") if len(ry) > 180 else ry,
        "genel_ozet": (genel[:200] + "…") if len(genel) > 200 else genel,
        "oncelik": list(getattr(danisman, "oncelik_sirasi", None) or [])[:3],
    }


def _plan_ozet(plan) -> Optional[Dict[str, Any]]:
    if plan is None:
        return None
    from karar_yorum import _plan_satirlari

    return {
        "girilen_tutar": _safe_float(getattr(plan, "girilen_tutar", None), 0),
        "para_birimi": getattr(plan, "para_birimi", ""),
        "tutar_tl": _safe_float(getattr(plan, "tutar_tl", None), 0),
        "mevcut_toplam_tl": _safe_float(getattr(plan, "mevcut_toplam_tl", None), 0),
        "yeni_toplam_tl": _safe_float(getattr(plan, "yeni_toplam_tl", None), 0),
        "rejim": getattr(plan, "rejim_etiket", "") or "",
        "satirlar": _plan_satirlari(plan),
        "notlar": list(getattr(plan, "notlar", None) or [])[:4],
    }


def _portfoy_ozet(varlik_store, varlik_deger=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"pozisyon_adet": 0, "ust_pozisyonlar": []}
    portfoy = None
    if varlik_store is not None and hasattr(varlik_store, "aktif"):
        try:
            portfoy = varlik_store.aktif()
        except Exception:
            portfoy = None
    if portfoy is None:
        return out

    pozlar = list(getattr(portfoy, "pozisyonlar", None) or [])
    out["pozisyon_adet"] = len(pozlar)
    out["portfoy_ad"] = getattr(portfoy, "ad", "") or ""

    deger_map: Dict[str, float] = {}
    toplam = None
    if varlik_deger is not None:
        raw_top = getattr(varlik_deger, "toplam", None)
        if isinstance(raw_top, dict):
            toplam = _safe_float(raw_top.get("TL"), 0)
        else:
            toplam = _safe_float(raw_top, 0)
        for pd_ in list(getattr(varlik_deger, "pozisyonlar", None) or []):
            poz = getattr(pd_, "pozisyon", None)
            pid = getattr(poz, "id", None) if poz is not None else None
            g = getattr(pd_, "guncel_deger", None)
            if pid and g is not None:
                try:
                    deger_map[str(pid)] = float(g)
                except (TypeError, ValueError):
                    pass
    if toplam is not None:
        out["toplam_deger_tl"] = toplam

    sirali = []
    for p in pozlar:
        pid = str(getattr(p, "id", "") or "")
        val = deger_map.get(pid)
        sirali.append((val if val is not None else 0.0, p, val))
    sirali.sort(key=lambda x: -x[0])

    for _, p, val in sirali[:MAX_POZISYON]:
        item = {
            "tur": getattr(p, "tur", ""),
            "sembol": getattr(p, "sembol", "") or "",
            "etiket": (getattr(p, "ad", None) or getattr(p, "sembol", "") or "")[:40],
        }
        if val is not None:
            item["deger"] = _safe_float(val, 0)
        out["ust_pozisyonlar"].append(item)
    return out


def _tefas_ozet(tefas_ham, n: int = MAX_TEFAS) -> List[dict]:
    if tefas_ham is None:
        return []
    fonlar = list(getattr(tefas_ham, "fonlar", None) or [])
    if not fonlar:
        return []
    try:
        fonlar = sorted(
            fonlar,
            key=lambda f: float(getattr(f, "skor", 0) or 0),
            reverse=True,
        )
    except Exception:
        pass
    out = []
    for f in fonlar[:n]:
        out.append({
            "kod": getattr(f, "kod", ""),
            "ad": (getattr(f, "kisa_ad", None) or getattr(f, "ad", "") or "")[:40],
            "kategori": getattr(f, "kategori", None) or getattr(f, "etkin_kategori", "") or "",
            "skor": _safe_float(getattr(f, "skor", None), 0),
            "oneri": getattr(f, "oneri", "") or "",
        })
    return out


def _hisse_odak_dict(h) -> Dict[str, Any]:
    from karar_yorum import _hisse_karar

    skor = getattr(h, "signal_v2_score", None)
    if skor is None:
        skor = getattr(h, "skor", None)
    alim = getattr(h, "signal_v2_al_price", None)
    if alim is None:
        alim = getattr(h, "yonetici_alim", None)
    return {
        "sembol": getattr(h, "sembol", ""),
        "ad": (getattr(h, "ad", "") or "")[:40],
        "piyasa": getattr(h, "piyasa", "") or getattr(h, "varlik_turu", ""),
        "karar": _hisse_karar(h),
        "skor": _safe_float(skor, 0),
        "1g_pct": _safe_float(getattr(h, "degisim_1g", None), 2),
        "alim_seviyesi": _safe_float(alim, 2),
        "neden": (getattr(h, "signal_v2_why", None) or getattr(h, "gerekce", "") or "")[:120],
    }


def _sembol_normalize(s: str) -> str:
    return (s or "").strip().upper()


def _sembol_kok(s: str) -> str:
    s = _sembol_normalize(s)
    if not s:
        return ""
    return s.split(".")[0].split("=")[0].split(":")[-1]


def baglam_sembol_allowlist(baglam: Dict[str, Any]) -> Set[str]:
    """Grounding için izinli sembol kökleri + tam ticker'lar."""
    allowed: Set[str] = set()

    def _add(raw: str) -> None:
        s = _sembol_normalize(raw)
        if not s or len(s) < 2:
            return
        allowed.add(s)
        kok = _sembol_kok(s)
        if kok:
            allowed.add(kok)

    for row in baglam.get("al_adaylari") or []:
        _add(str((row or {}).get("sembol") or ""))
    for row in baglam.get("izle_takip") or []:
        _add(str((row or {}).get("sembol") or ""))
    for row in baglam.get("endeksler") or []:
        _add(str((row or {}).get("sembol") or ""))
        _add(str((row or {}).get("ad") or ""))
    for row in baglam.get("tefas_ust") or []:
        _add(str((row or {}).get("kod") or ""))
    port = baglam.get("portfoy") or {}
    for row in port.get("ust_pozisyonlar") or []:
        _add(str((row or {}).get("sembol") or ""))
    odak = baglam.get("odak_sembol")
    if isinstance(odak, dict):
        _add(str(odak.get("sembol") or ""))
    plan = baglam.get("nakit_plani") or {}
    for row in plan.get("satirlar") or []:
        arac = str((row or {}).get("arac") or "")
        for tok in re.findall(r"[A-Za-z0-9.=]+", arac):
            if len(tok) >= 2:
                _add(tok)
    # Makro isimleri
    for x in ("VIX", "BIST", "GC", "GC=F", "XU100", "XU100.IS"):
        _add(x)
    return allowed


def odak_sembol_bul(user_msg: str, tarama=None, baglam: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Kullanıcı mesajında geçen tarama/portföy sembolünü detayla."""
    text = (user_msg or "").upper()
    if not text:
        return None

    candidates: List[Tuple[str, Any]] = []
    if tarama is not None:
        for h in list(getattr(tarama, "hisseler", None) or []):
            sym = _sembol_normalize(getattr(h, "sembol", "") or "")
            if sym:
                candidates.append((sym, h))
        for e in list(getattr(tarama, "endeksler", None) or []):
            sym = _sembol_normalize(getattr(e, "sembol", "") or "")
            if sym:
                candidates.append((sym, e))

    if baglam:
        for row in (baglam.get("al_adaylari") or []) + (baglam.get("izle_takip") or []):
            sym = _sembol_normalize(str((row or {}).get("sembol") or ""))
            if sym and not any(c[0] == sym for c in candidates):
                candidates.append((sym, row))

    # Uzun sembol önce (THYAO.IS > IS)
    candidates.sort(key=lambda x: -len(x[0]))
    for sym, obj in candidates:
        kok = _sembol_kok(sym)
        if sym and sym in text:
            if hasattr(obj, "sembol") or hasattr(obj, "signal_v2_decision"):
                return _hisse_odak_dict(obj)
            if isinstance(obj, dict):
                return dict(obj)
        if kok and len(kok) >= 3 and re.search(r"\b" + re.escape(kok) + r"\b", text):
            if hasattr(obj, "sembol") or hasattr(obj, "signal_v2_decision"):
                return _hisse_odak_dict(obj)
            if isinstance(obj, dict):
                return dict(obj)
    return None


def kaynak_dipnotu(baglam: Dict[str, Any]) -> str:
    """Motor üretir — LLM yazmaz."""
    parts: List[str] = []
    rejim = (baglam.get("rejim") or "").strip()
    if rejim:
        parts.append(f"rejim {rejim}")
    kod = (baglam.get("rejim_kod") or "").strip()
    if kod and kod not in rejim.upper():
        parts.append(kod)
    al_n = baglam.get("al_adet")
    if al_n is not None:
        parts.append(f"AL {al_n}")
    makro = baglam.get("makro") or {}
    vix = makro.get("vix")
    if vix is not None:
        parts.append(f"VIX {vix}")
    tahsis = baglam.get("tahsis_agirlik_pct") or {}
    if tahsis:
        top = sorted(tahsis.items(), key=lambda kv: -float(kv[1] or 0))[:2]
        parts.append("tahsis " + ", ".join(f"{k} %{v:g}" for k, v in top))
    odak = baglam.get("odak_sembol") or {}
    if isinstance(odak, dict) and odak.get("sembol"):
        parts.append(f"odak {odak.get('sembol')}")
    if not parts:
        return "_Kaynak: sistem özeti_"
    return "_Kaynak: " + " · ".join(parts) + "_"


def metinden_tickerlar(metin: str) -> List[str]:
    found = []
    for m in _TICKER_RE.finditer(metin or ""):
        tok = m.group(1)
        if tok in _TICKER_STOP:
            continue
        if len(_sembol_kok(tok)) < 2:
            continue
        if tok not in found:
            found.append(tok)
    return found


def ticker_grounding(
    metin: str,
    allowlist: Set[str],
) -> Tuple[str, List[str]]:
    """Allowlist dışı ticker'ları işaretle; metni olduğu gibi bırak, uyarı listesi döndür.

    Plan: cümleyi düşürme (agresif kırpma bozar); meta + dipnot uyarısı.
    """
    bad: List[str] = []
    for tok in metinden_tickerlar(metin):
        kok = _sembol_kok(tok)
        if tok in allowlist or kok in allowlist:
            continue
        # Kısa genel kelimeler
        if kok in _TICKER_STOP or tok in _TICKER_STOP:
            continue
        if tok not in bad:
            bad.append(tok)
    return metin, bad


def _temkinli_rejim(baglam: Dict[str, Any]) -> bool:
    kod = str(baglam.get("rejim_kod") or "").upper()
    if kod in ("KRIZ", "EM_STRES", "ENFLASYON_KORUMA"):
        return True
    etiket = str(baglam.get("rejim") or "").upper()
    if any(x in etiket for x in ("KRIZ", "STRES", "SAVUN", "TEMKIN")):
        return True
    vix = (baglam.get("makro") or {}).get("vix")
    try:
        if vix is not None and float(vix) >= VIX_TEMKIN_ESIK:
            return True
    except (TypeError, ValueError):
        pass
    return False


def sistem_baglam_ozeti(
    *,
    snap=None,
    tahsis=None,
    mevduat_ozet=None,
    tl_durum=None,
    tarama=None,
    danisman=None,
    varlik_store=None,
    varlik_deger=None,
    tefas_ham=None,
    plan=None,
    user_msg: str = "",
) -> Dict[str, Any]:
    """Token-dostu sistem özeti — sohbet system prompt'una girer."""
    from karar_yorum import (
        _endeks_ozeti,
        _fiili_sinif_pct,
        _tarama_al_listesi,
        _tarama_izle_listesi,
    )

    al_list = _tarama_al_listesi(tarama, n=MAX_AL)
    baglam: Dict[str, Any] = {
        "makro": _makro(snap),
        "rejim": _rejim_etiket(tahsis, plan),
        "rejim_kod": _rejim_kod(tahsis),
        "tahsis_agirlik_pct": _tahsis_pct(tahsis),
        "mevduat": _mevduat(mevduat_ozet),
        "tl_karar": _tl_karar(tl_durum),
        "endeksler": _endeks_ozeti(tarama),
        "al_adaylari": al_list,
        "al_adet": len(al_list),
        "izle_takip": _tarama_izle_listesi(tarama, n=MAX_IZLE),
        "danisman": _danisman_ozet(danisman),
        "fiili_sinif_pct": _fiili_sinif_pct(varlik_store, snap),
        "portfoy": _portfoy_ozet(varlik_store, varlik_deger),
        "tefas_ust": _tefas_ozet(tefas_ham, n=MAX_TEFAS),
        "nakit_plani": _plan_ozet(plan),
    }
    odak = odak_sembol_bul(user_msg, tarama=tarama, baglam=baglam)
    if odak:
        baglam["odak_sembol"] = odak
    baglam["temkinli_rejim"] = _temkinli_rejim(baglam)
    return baglam


def baglam_sikistir(baglam: Dict[str, Any]) -> Dict[str, Any]:
    """Prompt token diyeti — gereksiz alanları kes, yönlendirme alanlarını koru."""
    out = dict(baglam or {})
    endeksler = []
    for e in list(out.get("endeksler") or [])[:8]:
        endeksler.append({
            "ad": (e or {}).get("ad"),
            "sembol": (e or {}).get("sembol"),
            "1g_pct": (e or {}).get("1g_pct"),
            "1a_pct": (e or {}).get("1a_pct"),
            "oneri": (e or {}).get("oneri"),
            "neden": ((e or {}).get("neden") or "")[:70],
        })
    out["endeksler"] = endeksler
    al = []
    for a in list(out.get("al_adaylari") or [])[:MAX_AL]:
        al.append({
            "sembol": (a or {}).get("sembol"),
            "ad": (a or {}).get("ad"),
            "piyasa": (a or {}).get("piyasa"),
            "karar": (a or {}).get("karar"),
            "skor": (a or {}).get("skor"),
            "1g_pct": (a or {}).get("1g_pct"),
            "alim_seviyesi": (a or {}).get("alim_seviyesi"),
            "neden": ((a or {}).get("neden") or "")[:90],
        })
    out["al_adaylari"] = al
    out["al_adet"] = len(al)
    out["izle_takip"] = list(out.get("izle_takip") or [])[:MAX_IZLE]
    out["tefas_ust"] = list(out.get("tefas_ust") or [])[:MAX_TEFAS]
    port = dict(out.get("portfoy") or {})
    port["ust_pozisyonlar"] = list(port.get("ust_pozisyonlar") or [])[:MAX_POZISYON]
    out["portfoy"] = port
    plan = out.get("nakit_plani")
    if isinstance(plan, dict):
        out["nakit_plani"] = {
            "tutar_tl": plan.get("tutar_tl"),
            "para_birimi": plan.get("para_birimi"),
            "rejim": plan.get("rejim"),
            "satirlar": [
                {
                    "etiket": s.get("etiket"),
                    "oran_pct": s.get("oran_pct"),
                    "tutar_tl": s.get("tutar_tl"),
                    "arac": (s.get("arac") or "")[:50],
                    "gerekce": (s.get("gerekce") or "")[:80],
                }
                for s in list(plan.get("satirlar") or [])[:6]
            ],
            "notlar": list(plan.get("notlar") or [])[:3],
        }
    odak = out.get("odak_sembol")
    if isinstance(odak, dict):
        out["odak_sembol"] = {
            "sembol": odak.get("sembol"),
            "ad": odak.get("ad"),
            "piyasa": odak.get("piyasa"),
            "karar": odak.get("karar"),
            "skor": odak.get("skor"),
            "1g_pct": odak.get("1g_pct"),
            "alim_seviyesi": odak.get("alim_seviyesi"),
            "neden": (odak.get("neden") or "")[:120],
        }
    return out


def _system_prompt(baglam: Dict[str, Any]) -> str:
    kompakt = baglam_sikistir(baglam)
    veri = json.dumps(kompakt, ensure_ascii=False, indent=2, default=str)
    temkin = ""
    if baglam.get("temkinli_rejim"):
        temkin = (
            "\nREJİM KİLİDİ (zorunlu): Motor temkinli / kriz / yüksek VIX. "
            "Agresif alım dili kullanma; savunma, koru, bekle, kademeli dil.\n"
        )
    return f"""Sen Makrofinans / TL Yatırım Asistanı karar destek sohbet asistanısın.
Kullanıcı yönlendirme istiyor; VERİ yazılım motorundan gelir.
{temkin}
Yanıtı Türkçe, net ve **yeterince detaylı** yaz — şu yapıda (başlık kullan):

1) **Piyasa / rejim** — VIX, BIST, CDS, altın, EUR/TRY ve rejim; risk-on mu temkin mi (2–4 cümle).
2) **Ne yapılabilir** — tahsis / mevduat / TL tavanı / nakit planı varsa açıkla; yoksa atla.
3) **Hisse & ETF** — `al_adaylari` varsa sembol+piyasa+skor+alım seviyesi ile öncelik ver.
   AL yoksa açıkça bekle/İZLE de. `odak_sembol` varsa onu derinlemesine anlat.
4) **Endeksler** — Artır/Koru/Bekle/Azalt önerilerini kısaca yorumla.
5) **Bugün için net aksiyon** — 3 madde: (a) para/tahsis, (b) hisse, (c) neyi beklemeli.

Kurallar:
- Sadece VERİ'deki sembol/rakam; uydurma ticker yok.
- Yüzde / tutar yeniden hesaplama yok.
- "Kesinlikle al/sat" deme; "değerlendirilebilir / öncelikli aday / şimdilik bekle" kullan.
- Yasal uyarı veya "Kaynak:" satırı ekleme (sistem ekler).
- Bilgi yoksa "veride yok" de.
- Toplam ~12–20 cümle / maddeli; kısa tek paragraf yazma.

VERİ:
{veri}
"""


def _trim_history(
    history: Sequence[Dict[str, str]],
    *,
    max_turns: int = MAX_HISTORY_TURNS,
) -> List[Dict[str, str]]:
    """Son N user/assistant turunu koru (system hariç)."""
    cleaned: List[Dict[str, str]] = []
    for m in history or []:
        role = str((m or {}).get("role") or "").strip()
        content = str((m or {}).get("content") or "").strip()
        if role in ("user", "assistant") and content:
            if len(content) > 900:
                content = content[:900] + "…"
            cleaned.append({"role": role, "content": content})
    limit = max(2, int(max_turns) * 2)
    return cleaned[-limit:]


def asistan_yanit(
    baglam: Dict[str, Any],
    history: Sequence[Dict[str, str]],
    user_msg: str,
    *,
    timeout: float = API_TIMEOUT_SEC,
    _call_fn: Optional[Callable[[str], str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """(metin, meta). meta: model, provider, hata, hint, grounding_uyari."""
    provider = resolve_provider()
    model = resolve_model(provider)
    meta: Dict[str, Any] = {
        "model": model,
        "provider": provider,
        "hint": provider_hint(),
        "hata": None,
        "grounding_uyari": [],
    }
    soru = (user_msg or "").strip()
    if not soru:
        meta["hata"] = "empty"
        return "Bir soru yazın.", meta

    if not provider_ready() and _call_fn is None:
        meta["hata"] = "no_key"
        return FALLBACK + " " + provider_hint(), meta

    msgs = _trim_history(history)
    msgs.append({"role": "user", "content": soru})
    system = _system_prompt(baglam)

    try:
        metin = call_chat(
            messages=msgs,
            system=system,
            max_tokens=700,
            timeout=timeout,
            _call_fn=_call_fn,
        )
    except Exception as e:
        _log.warning("asistan_yanit: %s", e)
        meta["hata"] = str(e)
        err = str(e)
        if "429" in err or "daily_quota" in err:
            return FALLBACK + " " + MSG_429, meta
        if "403" in err or "1010" in err:
            return (
                FALLBACK + " (Groq erişim engeli — yenileyip tekrar deneyin.)",
                meta,
            )
        if "401" in err:
            return FALLBACK + " (API anahtarı geçersiz — `.env` GROQ_API_KEY.)", meta
        if "rate_limit" in err:
            return FALLBACK + " (Dakikalık istek limiti — biraz bekleyin.)", meta
        return FALLBACK, meta

    metin = (metin or "").strip() or FALLBACK
    allow = baglam_sembol_allowlist(baglam)
    metin, bad = ticker_grounding(metin, allow)
    meta["grounding_uyari"] = bad

    # Dipnot + grounding notu (motor)
    dip = kaynak_dipnotu(baglam)
    if bad:
        metin = (
            f"{metin}\n\n"
            f"_Not: Yanıtta veride olmayan sembol geçti ({', '.join(bad)}) — "
            f"yalnızca motor listesindeki ticker'lara güvenin._\n\n{dip}"
        )
    else:
        metin = f"{metin}\n\n{dip}"
    return metin, meta