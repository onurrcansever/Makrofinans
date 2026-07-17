# -*- coding: utf-8 -*-
"""
WhatsApp bildirim ekleri — yalnızca disk cache (API çağrısı yok).
Cache yoksa boş liste; bildirim yine gider.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import os

MAX_EK_KARAKTER = 200

_ANALIST_TR = {
    "strong_buy": "Güçlü Al",
    "buy": "Al",
    "hold": "Tut",
    "sell": "Sat",
    "strong_sell": "Güçlü Sat",
}


def _kisalt(metin: str, max_len: int = MAX_EK_KARAKTER) -> str:
    s = (metin or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _ilk_cumle(metin: str, *, max_cumle: int = 1, max_len: int = MAX_EK_KARAKTER) -> str:
    s = re.sub(r"\s+", " ", (metin or "").strip())
    if not s:
        return ""
    parcalar = re.split(r"(?<=[.!?…])\s+", s)
    alinan = " ".join(parcalar[:max_cumle]).strip()
    return _kisalt(alinan, max_len)


def _etf_mi(h) -> bool:
    return (
        getattr(h, "piyasa", "") == "ETF"
        or getattr(h, "varlik_turu", "") == "etf"
    )


def portfoy_degerle_guvenli(portfoy, snap, *, cache_salt: str = ""):
    """CI/alarm — önce hızlı mod (aninda), gerekirse tam fiyat çekimi."""
    import logging

    from varlik_fiyat import portfoy_degerle

    log = logging.getLogger(__name__)
    ci = bool(os.getenv("GITHUB_ACTIONS"))
    denemeler = (True, False) if ci else (False, True)
    son_exc: Optional[Exception] = None
    for aninda in denemeler:
        try:
            return portfoy_degerle(
                portfoy, snap, cache_salt=cache_salt, aninda=aninda,
            )
        except Exception as exc:
            son_exc = exc
            log.warning(
                "portfoy_degerle_guvenli (%s, aninda=%s): %s",
                cache_salt, aninda, exc,
            )
    if son_exc:
        raise son_exc
    raise RuntimeError("portfoy_degerle_guvenli: beklenmeyen durum")


def _temel_cache_oku(sembol: str) -> Dict[str, Any]:
    """API yok — yalnızca .temel_veri_cache.json."""
    try:
        from temel_veri import yukle_cache
        cache = yukle_cache()
    except Exception:
        return {}
    key = (sembol or "").strip().upper()
    ent = cache.get(key) or {}
    if not ent or ent.get("_bos"):
        # kök eşleşme (HALKB ↔ HALKB.IS)
        kok = key.split(".")[0]
        for k, v in cache.items():
            if str(k).split(".")[0] == kok and isinstance(v, dict) and not v.get("_bos"):
                return dict(v)
        return {}
    return dict(ent)


def temel_satiri_cache(h) -> Optional[str]:
    """📊 F/K: … | Analist: … | Hedef: … — ETF / cache yok → None."""
    if _etf_mi(h):
        return None
    temel = _temel_cache_oku(getattr(h, "sembol", "") or "")
    if not temel:
        return None
    if str(temel.get("quoteType") or "").upper() == "ETF":
        return None

    parcalar: List[str] = []
    fk = temel.get("trailingPE")
    try:
        if fk is not None and float(fk) > 0:
            parcalar.append(f"F/K: {float(fk):.1f}x")
    except (TypeError, ValueError):
        pass

    ak = temel.get("recommendationKey")
    if ak:
        etiket = _ANALIST_TR.get(str(ak).lower(), str(ak))
        n = temel.get("numberOfAnalystOpinions")
        try:
            n_i = int(float(n)) if n is not None else None
        except (TypeError, ValueError):
            n_i = None
        if n_i:
            parcalar.append(f"Analist: {n_i}→ {etiket}")
        else:
            parcalar.append(f"Analist: {etiket}")

    hedef = temel.get("targetMeanPrice")
    fiyat = temel.get("currentPrice") or temel.get("regularMarketPrice")
    try:
        if hedef is not None and fiyat is not None and float(fiyat) > 0:
            fark = (float(hedef) / float(fiyat) - 1.0) * 100.0
            parcalar.append(f"Hedef: {fark:+.0f}%")
    except (TypeError, ValueError):
        pass

    if not parcalar:
        return None
    return _kisalt("📊 " + " | ".join(parcalar))


def _llm_cache_oku(sembol: str, karar: str, skor: float) -> Optional[str]:
    """API yok — .llm_aciklama_cache.json."""
    try:
        from llm_aciklama import _cache_taze, cache_anahtar, yukle_cache
        cache = yukle_cache()
    except Exception:
        return None

    key = cache_anahtar(sembol, karar, skor)
    ent = cache.get(key)
    if ent and _cache_taze(ent) and ent.get("metin"):
        return str(ent["metin"])

    # Aynı sembol için taze herhangi bir kayıt
    sym = (sembol or "").strip().upper()
    kok = sym.split(".")[0]
    adaylar = []
    for k, v in cache.items():
        if not isinstance(v, dict) or not v.get("metin"):
            continue
        if not _cache_taze(v):
            continue
        vs = str(v.get("sembol") or k.split("|")[0]).upper()
        if vs == sym or vs.split(".")[0] == kok or k.upper().startswith(kok + "|"):
            adaylar.append(v)
    if not adaylar:
        return None
    adaylar.sort(key=lambda x: str(x.get("guncelleme") or ""), reverse=True)
    return str(adaylar[0]["metin"])


def ai_notu_cache(h) -> Optional[str]:
    """💬 tek cümle — cache yoksa None."""
    sembol = getattr(h, "sembol", "") or ""
    karar = getattr(h, "signal_v2_decision", "") or "AL"
    skor = getattr(h, "signal_v2_score", None)
    if skor is None:
        skor = getattr(h, "skor", 0) or 0
    metin = _llm_cache_oku(sembol, karar, float(skor))
    if not metin:
        return None
    cumle = _ilk_cumle(metin, max_cumle=1)
    if not cumle:
        return None
    return _kisalt(f"💬 {cumle}")


def sinyal_ek_satirlari(h) -> List[str]:
    """Temel + AI — her satır ≤200; yoksa boş."""
    out: List[str] = []
    t = temel_satiri_cache(h)
    if t:
        out.append(f"  {t}")
    a = ai_notu_cache(h)
    if a:
        out.append(f"  {a}")
    return out


def _portfoy_yorum_cache_son() -> Optional[Dict[str, Any]]:
    try:
        from portfoy_yorum import _cache_taze, yukle_cache
        cache = yukle_cache()
    except Exception:
        return None
    best = None
    best_ts = ""
    for ent in cache.values():
        if not isinstance(ent, dict) or not ent.get("metin"):
            continue
        if not _cache_taze(ent):
            continue
        ts = str(ent.get("guncelleme") or "")
        if ts >= best_ts:
            best_ts = ts
            best = ent
    return best


def portfoy_durum_satirlari(
    snap=None,
    tarama=None,
    *,
    kz_pct_override: Optional[float] = None,
) -> List[str]:
    """
    📋 PORTFÖY DURUMU bloğu.
    Metrikler: yerel hesap (API yok). 💬 yalnızca cache.
    """
    ozet: Dict[str, Any] = {}
    try:
        from portfoy_yorum import portfoy_ozet_hesapla
        from varliklarim import yukle_store

        store = yukle_store()
        portfoy = store.aktif()
        if not portfoy or not portfoy.pozisyonlar:
            return []
        deger_poz = None
        if snap is not None:
            try:
                deger = portfoy_degerle_guvenli(portfoy, snap, cache_salt="bildirim_ek")
                deger_poz = deger.pozisyonlar
                maliyet = deger.maliyet_toplam.get("TL", 0) or 0
                toplam = deger.toplam.get("TL", 0) or 0
                if maliyet > 0 and kz_pct_override is None:
                    kz_pct_override = (toplam - maliyet) / maliyet * 100.0
            except Exception:
                deger_poz = None
        ozet = portfoy_ozet_hesapla(
            portfoy.pozisyonlar,
            tarama.hisseler if tarama and hasattr(tarama, "hisseler") else tarama,
            deger_pozisyonlar=deger_poz,
        )
        if kz_pct_override is not None:
            ozet["portfoy_kz_pct"] = round(float(kz_pct_override), 1)
    except Exception:
        # Cache'deki ozet yedek
        ent = _portfoy_yorum_cache_son()
        if not ent or not ent.get("ozet"):
            return []
        ozet = dict(ent["ozet"])

    if not ozet:
        return []

    ort = int(ozet.get("ortalama_skor") or 0)
    kz = float(ozet.get("portfoy_kz_pct") or 0)
    azalt = float(ozet.get("azalt_agirlik_pct") or 0)
    kz_s = f"{kz:+.1f}".replace(".", ",")
    azalt_s = f"{azalt:.1f}".replace(".", ",")
    satirlar = [
        "📋 PORTFÖY DURUMU",
        f"Ort. sinyal: {ort}/100 | K/Z: {kz_s}%",
    ]
    if azalt > 0:
        satirlar.append(f"⚠ AZALT sinyalli pozisyonlar: %{azalt_s}")

    ent = _portfoy_yorum_cache_son()
    if ent and ent.get("metin"):
        yorum = _ilk_cumle(str(ent["metin"]), max_cumle=2)
        if yorum:
            satirlar.append(_kisalt(f"💬 {yorum}"))
    return satirlar


def _bildirim_gosterim_pb() -> str:
    import config
    from fiyat_para import GOSTERIM_PB_LIST

    pb = (getattr(config, "OZET_GOSTERIM_PB", None) or os.getenv("OZET_GOSTERIM_PB", "EUR")).upper()
    return pb if pb in GOSTERIM_PB_LIST else "EUR"


def _fmt_kz_pct(pct: float) -> str:
    return f"{pct:+.1f}".replace(".", ",") + "%"


def _tablo_kisalt(metin: str, max_len: int) -> str:
    s = (metin or "—").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _tefas_bildirim_yukle(snap, tarama, profil, gosterim_pb: str, pozisyonlar) -> tuple:
    """TEFAS fon skoru — portföyde fon varsa (API, tarama ile aynı tur)."""
    if not any(getattr(p, "tur", "") == "tefas" for p in pozisyonlar):
        return None, None
    try:
        from allocation_engine import tahsis_hesapla
        from app_veri import tefas_ham_cek, tefas_yukleniyor
        from fiyat_para import tablo_fx_hazirla
        from investor_profile import YatirimProfili
        from tefas_skor import tefas_skorlu_kopya

        tefas_ham = tefas_ham_cek(120, 0)
        if not tefas_ham or tefas_yukleniyor(tefas_ham) or getattr(tefas_ham, "hata", ""):
            return tefas_ham, None
        prof = profil or YatirimProfili()
        tahsis = tahsis_hesapla(snap, prof)
        fx, eur_s, usd_s, gbp_s, _ = tablo_fx_hazirla(snap, tarama)
        tefas_skorlu = tefas_skorlu_kopya(
            tefas_ham, prof, tahsis.rejim.rejim,
            gosterim_pb=gosterim_pb,
            eur_seri=eur_s, usd_seri=usd_s, gbp_seri=gbp_s,
        )
        return tefas_ham, tefas_skorlu
    except Exception:
        return None, None


def portfoy_pozisyon_tablo_satirlari(
    snap=None,
    tarama=None,
    profil=None,
    *,
    gosterim_pb: Optional[str] = None,
) -> List[str]:
    """
    WhatsApp düz metin pozisyon tablosu — Varlıklarım ile aynı sinyal/öneri mantığı.
    """
    import config

    if not getattr(config, "OZET_POZISYON_TABLO", True):
        return []
    if snap is None:
        return []

    gpb = (gosterim_pb or _bildirim_gosterim_pb()).upper()
    try:
        from portfoy_yoneticisi import (
            POZ_COL_ONERI,
            POZ_COL_SINYAL,
            pozisyon_oneri_etiket,
            yonetici_pozisyon_kolonlari,
        )
        from varliklarim import yukle_store

        store = yukle_store()
        portfoy = store.aktif()
        if not portfoy or not portfoy.pozisyonlar:
            return []

        deger = portfoy_degerle_guvenli(portfoy, snap, cache_salt="bildirim_poz_tab")
        tefas_ham, tefas_skorlu = _tefas_bildirim_yukle(
            snap, tarama, profil, gpb, portfoy.pozisyonlar,
        )
        from fiyat_para import tablo_fx_hazirla
        fx, *_ = tablo_fx_hazirla(snap, tarama)

        rows: List[tuple] = []
        for pd_ in deger.pozisyonlar:
            p = pd_.pozisyon
            kol = yonetici_pozisyon_kolonlari(
                p, pd_,
                tarama=tarama,
                tefas_ham=tefas_ham,
                tefas_skorlu=tefas_skorlu,
                gosterim_pb=gpb,
                fx=fx,
            )
            ad = _tablo_kisalt(p.etiket(), 12)
            sinyal = _tablo_kisalt(str(kol.get(POZ_COL_SINYAL) or "—"), 8)
            oneri = _tablo_kisalt(pozisyon_oneri_etiket(kol.get(POZ_COL_ONERI)), 16)
            kz = _fmt_kz_pct(float(pd_.kar_zarar_pct or 0))
            emir_kod = ""
            oneri_h = kol.get(POZ_COL_ONERI)
            if isinstance(oneri_h, dict):
                emir_kod = str(oneri_h.get("code") or "")
            oncelik = 0
            if emir_kod in ("Sat", "Kâr Al", "Azalt"):
                oncelik = 2
            elif emir_kod in ("Ekle", "Bekle"):
                oncelik = 1
            rows.append((oncelik, abs(pd_.kar_zarar_pct or 0), ad, sinyal, oneri, kz, emir_kod))

        if not rows:
            return []

        rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
        cap = int(getattr(config, "OZET_POZ_MAX", 0) or 0)
        if cap > 0:
            rows = rows[:cap]

        satirlar = [f"📊 POZİSYONLAR ({gpb})", "Araç · Sinyal · Öneri · K/Z"]
        for _, __, ad, sinyal, oneri, kz, emir_kod in rows:
            isaret = ""
            if emir_kod in ("Kâr Al", "Sat", "Azalt"):
                isaret = "⚠ "
            satirlar.append(f"{isaret}{ad} · {sinyal} · {oneri} · {kz}")
        return satirlar
    except Exception:
        return []
