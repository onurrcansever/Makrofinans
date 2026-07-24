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
    "Bugün piyasaları yorumla",
    "Bugün ne yapayım?",
    "AL adaylarım neler?",
    "TL mi altın mı?",
    "Portföyüm rejimle uyumlu mu?",
)
PLAN_SORUSU = "Son nakit planımı açıkla"
PIYASA_OZET_SORUSU = "Bugün piyasaları yorumla"


def _safe_float(x: Any, nd: int = 1) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _fmt_pct(x: Any, *, signed: bool = True, nd: int = 1) -> str:
    v = _safe_float(x, nd)
    if v is None:
        return "—"
    if signed and v > 0:
        return f"+{v:.{nd}f}%"
    return f"{v:.{nd}f}%"


def _fmt_tl(x: Any) -> str:
    v = _safe_float(x, 0)
    if v is None:
        return "—"
    return f"{v:,.0f} TL"


def _piyasa_ozet_sorusu_mu(msg: str) -> bool:
    m = (msg or "").strip().lower()
    if not m:
        return False
    if m == PIYASA_OZET_SORUSU.lower():
        return True
    return "piyasalar" in m and "yorumla" in m


def _makro(snap) -> Dict[str, Any]:
    if snap is None:
        return {}
    from petrol_enflasyon_uyari import petrol_enflasyon_uyarisi

    v = getattr(snap, "veri", None)
    brent_3a = _safe_float(getattr(snap, "brent_3a_degisim", None), 1)
    petrol_uyari = petrol_enflasyon_uyarisi(brent_3a)
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
        "brent_usd": _safe_float(getattr(snap, "brent_usd", None), 1),
        "brent_1g_pct": _safe_float(getattr(snap, "brent_1g_degisim", None), 2),
        "brent_3a_pct": brent_3a,
        "petrol_enflasyon_uyari": petrol_uyari["mesaj"] if petrol_uyari else None,
        "dxy": _safe_float(getattr(snap, "dxy", None), 1),
        "dxy_1g_pct": _safe_float(getattr(snap, "dxy_1g_degisim", None), 2),
        "abd_10y": _safe_float(getattr(snap, "abd_10y", None), 2),
        "abd_10y_1g_pct": _safe_float(getattr(snap, "abd_10y_1g_degisim", None), 2),
        "abd_30y": _safe_float(getattr(snap, "abd_30y", None), 2),
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
    kz_map: Dict[str, float] = {}
    getiri_map: Dict[str, float] = {}
    toplam = None
    if varlik_deger is not None:
        raw_top = getattr(varlik_deger, "toplam", None)
        if isinstance(raw_top, dict):
            toplam = _safe_float(raw_top.get("TL"), 0)
        else:
            toplam = _safe_float(raw_top, 0)
        ag = getattr(varlik_deger, "agirlikli_getiri", None) or {}
        out["agirlikli_getiri"] = {
            str(k): _safe_float(v, 2) for k, v in ag.items() if v is not None
        }
        mal = getattr(varlik_deger, "maliyet_toplam", None)
        if isinstance(mal, dict):
            out["maliyet_tl"] = _safe_float(mal.get("TL"), 0)
        for pd_ in list(getattr(varlik_deger, "pozisyonlar", None) or []):
            poz = getattr(pd_, "pozisyon", None)
            pid = getattr(poz, "id", None) if poz is not None else None
            g = getattr(pd_, "guncel_deger", None)
            if pid and g is not None:
                try:
                    deger_map[str(pid)] = float(g)
                except (TypeError, ValueError):
                    pass
            if pid:
                kz = getattr(pd_, "kar_zarar_pct", None)
                if kz is not None:
                    try:
                        kz_map[str(pid)] = float(kz)
                    except (TypeError, ValueError):
                        pass
                g1 = (getattr(pd_, "getiriler", None) or {}).get("1G")
                if g1 is not None:
                    try:
                        getiri_map[str(pid)] = float(g1)
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
        pid = str(getattr(p, "id", "") or "")
        item = {
            "tur": getattr(p, "tur", ""),
            "sembol": getattr(p, "sembol", "") or "",
            "etiket": (getattr(p, "ad", None) or getattr(p, "sembol", "") or "")[:40],
        }
        if val is not None:
            item["deger"] = _safe_float(val, 0)
        if pid in kz_map:
            item["kz_pct"] = _safe_float(kz_map[pid], 1)
        if pid in getiri_map:
            item["getiri_1g"] = _safe_float(getiri_map[pid], 2)
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
        item = {
            "kod": getattr(f, "kod", ""),
            "ad": (getattr(f, "kisa_ad", None) or getattr(f, "ad", "") or "")[:40],
            "kategori": getattr(f, "kategori", None) or getattr(f, "etkin_kategori", "") or "",
            "skor": _safe_float(getattr(f, "skor", None), 0),
            "oneri": getattr(f, "oneri", "") or "",
            "akran_kucuk": bool(getattr(f, "akran_kucuk", False)),
            "skor_notu": (getattr(f, "skor_notu", "") or "")[:120],
        }
        for attr, key in (
            ("getiri_gosterim_1a", "getiri_1a"),
            ("getiri_gosterim_3a", "getiri_3a"),
            ("getiri_gosterim_ybb", "getiri_ybb"),
            ("stopaj_etiket", "stopaj"),
            ("tgo_pct", "tgo_pct"),
            ("yonetim_ucreti_pct", "yon_pct"),
        ):
            v = getattr(f, attr, None)
            if v is not None and v != "":
                item[key] = v if isinstance(v, str) else _safe_float(v, v)
        out.append(item)
    return out


def _tarama_hareket_ozeti(tarama, *, n: int = 3) -> Dict[str, Any]:
    """Piyasa bazlı AL/İZLE sayısı ve günlük hareket liderleri."""
    from karar_yorum import _hisse_karar

    out: Dict[str, Any] = {
        "al_sayisi": {},
        "izle_sayisi": {},
        "yukselenler": [],
        "dusenler": [],
    }
    if tarama is None:
        return out
    hisseler = list(getattr(tarama, "hisseler", None) or [])
    hareket = []
    for h in hisseler:
        piyasa = getattr(h, "piyasa", "") or getattr(h, "varlik_turu", "") or "?"
        karar = _hisse_karar(h)
        if karar in ("AL", "GÜÇLÜ AL"):
            out["al_sayisi"][piyasa] = out["al_sayisi"].get(piyasa, 0) + 1
        elif karar == "İZLE":
            out["izle_sayisi"][piyasa] = out["izle_sayisi"].get(piyasa, 0) + 1
        d1 = getattr(h, "degisim_1g", None)
        if d1 is None:
            continue
        try:
            d1f = float(d1)
        except (TypeError, ValueError):
            continue
        hareket.append({
            "sembol": getattr(h, "sembol", ""),
            "ad": (getattr(h, "ad", "") or "")[:24],
            "piyasa": piyasa,
            "1g_pct": _safe_float(d1f, 2),
            "karar": karar,
        })
    hareket.sort(key=lambda x: -(x.get("1g_pct") or 0))
    out["yukselenler"] = hareket[:n]
    out["dusenler"] = list(reversed(hareket[-n:])) if len(hareket) >= n else list(reversed(hareket))
    return out


def _makro_satirlari(makro: Dict[str, Any]) -> List[str]:
    satirlar: List[str] = []
    if makro.get("eur_try") is not None:
        satirlar.append(
            f"EUR/TRY {makro['eur_try']:.2f} ({_fmt_pct(makro.get('eur_try_1g_pct'))} 1G)"
        )
    if makro.get("cds_5y_bp") is not None:
        satirlar.append(f"CDS 5Y {makro['cds_5y_bp']:.0f} bp")
    if makro.get("vix") is not None:
        satirlar.append(
            f"VIX {makro['vix']:.1f} ({_fmt_pct(makro.get('vix_1g_pct'))} 1G)"
        )
    if makro.get("bist100") is not None:
        satirlar.append(
            f"BIST 100 {makro['bist100']:,.0f} ({_fmt_pct(makro.get('bist100_1g_pct'))} 1G)"
        )
    if makro.get("bist_vol_30g") is not None:
        satirlar.append(f"BIST vol (30g) {makro['bist_vol_30g']:.1f}")
    if makro.get("altin_usd") is not None:
        satirlar.append(
            f"Altın ${makro['altin_usd']:,.0f} ({_fmt_pct(makro.get('altin_1g_pct'))} 1G)"
        )
    if makro.get("brent_usd") is not None:
        brent_line = f"Brent ${makro['brent_usd']:,.1f} ({_fmt_pct(makro.get('brent_1g_pct'))} 1G"
        b3 = makro.get("brent_3a_pct")
        if b3 is not None:
            brent_line += f", {_fmt_pct(b3)} 3A"
        brent_line += ")"
        satirlar.append(brent_line)
    if makro.get("dxy") is not None:
        satirlar.append(
            f"DXY {makro['dxy']:.1f} ({_fmt_pct(makro.get('dxy_1g_pct'))} 1G)"
        )
    if makro.get("abd_10y") is not None:
        abd1g = makro.get("abd_10y_1g_pct")
        abd1g_s = f" ({_fmt_pct(abd1g, nd=2)} 1G)" if abd1g is not None else ""
        satirlar.append(f"ABD 10Y %{makro['abd_10y']:.2f}{abd1g_s}")
    if makro.get("abd_30y") is not None:
        satirlar.append(f"ABD 30Y %{makro['abd_30y']:.2f}")
    if makro.get("enflasyon_tr") is not None:
        satirlar.append(f"TÜFE (yıllık ref.) %{makro['enflasyon_tr']:.1f}")
    return satirlar


def gunluk_piyasa_ozeti_metni(baglam: Dict[str, Any]) -> str:
    """Motordan deterministik günlük piyasa özeti — LLM kotası olmadan da çalışır."""
    makro = baglam.get("makro") or {}
    rejim = (baglam.get("rejim") or "—").replace("_", " ")
    mevduat = baglam.get("mevduat") or {}
    tl_karar = baglam.get("tl_karar") or {}
    danisman = baglam.get("danisman") or {}
    endeksler = list(baglam.get("endeksler") or [])
    al_list = list(baglam.get("al_adaylari") or [])
    izle_list = list(baglam.get("izle_takip") or [])
    tefas = list(baglam.get("tefas_ust") or [])
    portfoy = baglam.get("portfoy") or {}
    tahsis = baglam.get("tahsis_agirlik_pct") or {}
    hareket = baglam.get("tarama_hareket") or {}

    parcalar: List[str] = [
        "### Bugünün piyasa özeti",
        "",
        f"**Makro rejim:** {rejim}",
    ]
    if danisman.get("rejim_yorumu"):
        parcalar.append(f"_{danisman['rejim_yorumu']}_")
    makro_sat = _makro_satirlari(makro)
    if makro_sat:
        parcalar.extend(["", "**Makro göstergeler**", " · ".join(makro_sat)])
    if makro.get("petrol_enflasyon_uyari"):
        parcalar.append(f"⛽ {makro['petrol_enflasyon_uyari']}")
    if mevduat.get("net_pct") is not None:
        reel = mevduat.get("reel_pp")
        reel_s = f", reel {_fmt_pct(reel, nd=1)}" if reel is not None else ""
        parcalar.append(
            f"TL mevduat (profil): net %{mevduat['net_pct']:.1f}{reel_s}"
        )
    if tl_karar.get("baslik"):
        tavan = tl_karar.get("tavan_pct")
        tavan_s = f" · tavan %{tavan:.0f}" if tavan is not None else ""
        parcalar.append(f"TL tavanı: {tl_karar['baslik']}{tavan_s}")
    if tahsis:
        top = sorted(tahsis.items(), key=lambda kv: -float(kv[1] or 0))[:4]
        parcalar.append(
            "**Önerilen tahsis:** "
            + ", ".join(f"{k.replace('_', ' ')} %{v:g}" for k, v in top)
        )

    if endeksler:
        parcalar.extend(["", "**Endeksler**"])
        for e in endeksler[:8]:
            ad = (e or {}).get("ad") or (e or {}).get("sembol") or "—"
            parcalar.append(
                f"- {ad}: {_fmt_pct((e or {}).get('1g_pct'))} 1G · "
                f"{_fmt_pct((e or {}).get('1a_pct'))} 1A · "
                f"öneri **{(e or {}).get('oneri') or '—'}**"
            )

    al_say = hareket.get("al_sayisi") or {}
    izle_say = hareket.get("izle_sayisi") or {}
    if al_say or izle_say or al_list:
        parcalar.extend(["", "**Hisse & ETF taraması**"])
        if al_say:
            parcalar.append(
                "AL sayısı: "
                + ", ".join(f"{p} {n}" for p, n in sorted(al_say.items(), key=lambda x: -x[1]))
            )
        if izle_say:
            parcalar.append(
                "İZLE sayısı: "
                + ", ".join(f"{p} {n}" for p, n in sorted(izle_say.items(), key=lambda x: -x[1]))
            )
        if al_list:
            parcalar.append("**Öncelikli AL adayları** (hemen al emri değil):")
            for a in al_list[:6]:
                parcalar.append(
                    f"- **{(a or {}).get('sembol')}** ({(a or {}).get('piyasa')}) "
                    f"skor {(a or {}).get('skor')} · {(a or {}).get('karar')} · "
                    f"{_fmt_pct((a or {}).get('1g_pct'))} 1G"
                    + (
                        f" · alım ~{(a or {}).get('alim_seviyesi')}"
                        if (a or {}).get("alim_seviyesi") is not None
                        else ""
                    )
                )
        elif not al_say:
            parcalar.append("_Bugün AL adayı yok — tarama boş veya eşik altında._")
        if izle_list:
            izle_txt = ", ".join(
                f"{(x or {}).get('sembol')} ({(x or {}).get('piyasa')}, skor {(x or {}).get('skor')})"
                for x in izle_list[:4]
            )
            parcalar.append(f"**İZLE takip:** {izle_txt}")
        yuks = hareket.get("yukselenler") or []
        dus = hareket.get("dusenler") or []
        if yuks:
            parcalar.append(
                "**Günün yükselenleri:** "
                + " · ".join(
                    f"{x.get('sembol')} {_fmt_pct(x.get('1g_pct'))}"
                    for x in yuks if x.get("1g_pct") is not None
                )
            )
        if dus:
            parcalar.append(
                "**Günün düşenleri:** "
                + " · ".join(
                    f"{x.get('sembol')} {_fmt_pct(x.get('1g_pct'))}"
                    for x in dus if x.get("1g_pct") is not None
                )
            )

    if tefas:
        parcalar.extend(["", "**TEFAS fonlar** (üst skor — TEFAS AL ≠ hisse AL)"])
        for f in tefas[:5]:
            parcalar.append(
                f"- **{(f or {}).get('kod')}** {(f or {}).get('ad')} · "
                f"skor {(f or {}).get('skor')} · {(f or {}).get('oneri') or '—'}"
            )

    poz_adet = portfoy.get("pozisyon_adet") or 0
    if poz_adet:
        parcalar.extend(["", "**Portföyünüz**"])
        if portfoy.get("toplam_deger_tl") is not None:
            parcalar.append(f"Toplam: {_fmt_tl(portfoy['toplam_deger_tl'])}")
        ag = portfoy.get("agirlikli_getiri") or {}
        if ag.get("1G") is not None:
            parcalar.append(f"Ağırlıklı getiri: {_fmt_pct(ag['1G'])} 1G")
        ust = list(portfoy.get("ust_pozisyonlar") or [])
        if ust:
            parcalar.append("Pozisyonlar:")
            for p in ust[:6]:
                sat = (
                    f"- **{(p or {}).get('sembol') or (p or {}).get('etiket')}** "
                    f"({_fmt_tl((p or {}).get('deger'))})"
                )
                ek = []
                if (p or {}).get("getiri_1g") is not None:
                    ek.append(f"1G {_fmt_pct((p or {}).get('getiri_1g'))}")
                if (p or {}).get("kz_pct") is not None:
                    ek.append(f"K/Z {_fmt_pct((p or {}).get('kz_pct'))}")
                if ek:
                    sat += " · " + " · ".join(ek)
                parcalar.append(sat)
    else:
        parcalar.extend(["", "**Portföyünüz:** _Kayıtlı pozisyon yok._"])

    # Net aksiyon — rejime göre kısa mentor notu
    parcalar.extend(["", "**Bugün için 3 madde**"])
    vix = makro.get("vix")
    temkin = baglam.get("temkinli_rejim") or (vix is not None and float(vix) >= VIX_TEMKIN_ESIK)
    if temkin:
        parcalar.append("1. **Para/tahsis:** Savunmacı kal — agresif alım diline kapalı rejim.")
    elif al_list:
        parcalar.append(
            "1. **Para/tahsis:** Rejim tahsisine uy; yeni para varsa planlı dağıt, tek seferde değil."
        )
    else:
        parcalar.append("1. **Para/tahsis:** Nakit/tahsis planına sadık kal; acele genişleme yok.")
    if al_list:
        top = al_list[0]
        parcalar.append(
            f"2. **Hisse/ETF:** Önce **{top.get('sembol')}** ({top.get('piyasa')}) "
            f"izle — skor {top.get('skor')}, alım seviyesi yakın mı kontrol et."
        )
    else:
        parcalar.append("2. **Hisse/ETF:** AL yok — İZLE listesini ve endeks önerilerini takip et.")
    if makro.get("petrol_enflasyon_uyari"):
        parcalar.append("3. **Bekle:** Petrol kaynaklı enflasyon baskısı — TÜİK öncesi reel getiriyi izle.")
    elif temkin:
        parcalar.append("3. **Bekle:** VIX/rejim temkinli — netleşene kadar küçük adım.")
    else:
        parcalar.append("3. **Bekle:** Makro (CDS, kur, ABD tahvil) ve AL seviyelerinde onay bekle.")

    parcalar.append("")
    parcalar.append("_Yatırım tavsiyesi değildir; rakamlar yazılım motorundan._")
    return "\n".join(parcalar)


def _hisse_odak_dict(h) -> Dict[str, Any]:
    from karar_yorum import _hisse_karar
    from signal_engine.explain.tech_snapshot import tech_snapshot_from_hisse

    skor = getattr(h, "signal_v2_score", None)
    if skor is None:
        skor = getattr(h, "skor", None)
    alim = getattr(h, "signal_v2_al_price", None)
    if alim is None:
        alim = getattr(h, "yonetici_alim", None)
    out: Dict[str, Any] = {
        "sembol": getattr(h, "sembol", ""),
        "ad": (getattr(h, "ad", "") or "")[:40],
        "piyasa": getattr(h, "piyasa", "") or getattr(h, "varlik_turu", ""),
        "karar": _hisse_karar(h),
        "skor": _safe_float(skor, 0),
        "1g_pct": _safe_float(getattr(h, "degisim_1g", None), 2),
        "alim_seviyesi": _safe_float(alim, 2),
        "neden": (getattr(h, "signal_v2_why", None) or getattr(h, "gerekce", "") or "")[:120],
    }
    try:
        snap = tech_snapshot_from_hisse(h)
        out["teknik"] = snap.asistan_odak_dict()
    except Exception:
        pass
    return out


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
        "tarama_hareket": _tarama_hareket_ozeti(tarama),
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
        teknik = odak.get("teknik") if isinstance(odak.get("teknik"), dict) else {}
        out["odak_sembol"] = {
            "sembol": odak.get("sembol"),
            "ad": odak.get("ad"),
            "piyasa": odak.get("piyasa"),
            "karar": odak.get("karar"),
            "skor": odak.get("skor"),
            "1g_pct": odak.get("1g_pct"),
            "alim_seviyesi": odak.get("alim_seviyesi"),
            "neden": (odak.get("neden") or "")[:120],
            "teknik": {
                "rsi": teknik.get("rsi"),
                "rsi_okuma": teknik.get("rsi_okuma"),
                "sma20_okuma": teknik.get("sma20_okuma"),
                "sma50_okuma": teknik.get("sma50_okuma"),
                "sma200_okuma": teknik.get("sma200_okuma"),
                "kisa_okuma": (teknik.get("kisa_okuma") or "")[:100],
                "uzun_okuma": (teknik.get("uzun_okuma") or "")[:100],
                "ozet": (teknik.get("ozet") or "")[:120],
                "al_seviyesi": teknik.get("al_seviyesi"),
                "spot_near": teknik.get("spot_near"),
                "ichimoku_buy_zone": teknik.get("ichimoku_buy_zone"),
                "ichimoku_note": (teknik.get("ichimoku_note") or "")[:100],
                "aksiyon_okuma": (teknik.get("aksiyon_okuma") or "")[:160],
            } if teknik else None,
        }
    return out


def _piyasa_ozet_system_prompt(baglam: Dict[str, Any]) -> str:
    """Günlük piyasa yorumu — mentor tonu, tüm makro/tarama/portföy bölümleri."""
    kompakt = baglam_sikistir(baglam)
    # Motor iskeleti LLM'e zorunlu rakam listesi olarak gider (uydurma önler)
    motor_iskelet = gunluk_piyasa_ozeti_metni(baglam)
    veri = json.dumps(kompakt, ensure_ascii=False, indent=2, default=str)
    temkin = ""
    if baglam.get("temkinli_rejim"):
        temkin = (
            "\nREJİM KİLİDİ: temkinli / yüksek VIX — agresif alım dili yok.\n"
        )
    return f"""Sen deneyimli bir makro/portföy mentorusun. Kullanıcı «Bugün piyasaları yorumla» dedi.
{temkin}
Görevin: MOTOR_ISKELET ve VERİ'deki rakamları mentor dilinde, akıcı Türkçe ile yorumlamak.
Tüm başlıkları kapsa (eksik bırakma):

1) **Makro & rejim** — CDS, VIX, BIST, Brent, DXY, ABD 10Y/30Y, EUR/TRY, altın, enflasyon; rejim ne anlama geliyor.
2) **Tahsis / TL** — önerilen tahsis, mevduat net/reel, TL tavanı (VERİ'de varsa).
3) **Endeksler** — her endeks için kısa okuma (öneri + 1G).
4) **Hisse & ETF** — AL yoksa net söyle; İZLE ve günün yükselen/düşenlerini yorumla.
5) **TEFAS** — üst fonları kısaca; TEFAS AL ≠ hisse AL uyarısını unutma.
6) **Portföyünüz** — toplam, 1G, pozisyon hareketleri (VERİ'de yoksa «kayıtlı pozisyon yok»).
7) **Bugün için 3 madde** — (a) para, (b) hisse/fon, (c) neyi beklemeli.

Kurallar:
- Sadece VERİ / MOTOR_ISKELET rakam ve sembolleri; uydurma yok.
- Mentor tonu: «bugün şöyle okuyorum / şunu izlerdim» — «kesinlikle al/sat» yok.
- Yüzde/tutar yeniden hesaplama yok.
- Yasal uyarı veya «Kaynak:» satırı yazma (sistem ekler).
- ~15–25 cümle; maddeli başlıklar kullan.

MOTOR_ISKELET:
{motor_iskelet}

VERİ:
{veri}
"""


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
   AL yoksa açıkça bekle/İZLE de. `odak_sembol` varsa onu derinlemesine anlat:
   teknik (RSI/SMA), Ichimoku bekle/açık, analist yoksa «veride yok»,
   motor seviyesi + «şu civardan değerlendir / şunu bekle» dili kullan.
   Listede AL = hemen al emri değildir.
4) **TEFAS fonlar** — `tefas_ust` varsa: uyum skoru / öneri; **TEFAS AL ≠ hisse AL / hemen al**.
   Brüt getiri; stopaj ve ücret VERİ’de yoksa uydurma — «veride yok» de.
   `akran_kucuk` veya YBB felaket notu varsa uyar.
5) **Endeksler** — Artır/Koru/Bekle/Azalt önerilerini kısaca yorumla (ağırlık; hisse AL iptali değil).
6) **Bugün için net aksiyon** — 3 madde: (a) para/tahsis, (b) hisse, (c) neyi beklemeli.

Kurallar:
- Sadece VERİ'deki sembol/rakam; uydurma ticker yok.
- Yüzde / tutar yeniden hesaplama yok.
- "Kesinlikle al/sat" deme; "değerlendirilebilir / öncelikli aday / şimdilik bekle" kullan.
- Stopaj / TGO / ücret rakamı VERİ’de yoksa uydurma.
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

    if _piyasa_ozet_sorusu_mu(soru):
        motor_metin = gunluk_piyasa_ozeti_metni(baglam)
        # #region agent log
        try:
            import time as _t
            with open(
                "/Users/onurcansever/Desktop/tl-yatirim-asistani/.cursor/debug-715414.log",
                "a",
                encoding="utf-8",
            ) as _df:
                _df.write(
                    json.dumps(
                        {
                            "sessionId": "715414",
                            "runId": "piyasa-llm-hybrid",
                            "hypothesisId": "H1",
                            "location": "asistan_chat.py:asistan_yanit",
                            "message": "piyasa ozet path",
                            "data": {
                                "provider_ready": provider_ready() or _call_fn is not None,
                                "has_mock": _call_fn is not None,
                                "motor_len": len(motor_metin or ""),
                            },
                            "timestamp": int(_t.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
        # LLM yoksa motor iskeleti (eski "uyarı" hissi veren dry dump)
        if not provider_ready() and _call_fn is None:
            meta["hata"] = "no_key"
            meta["hint"] = "Motordan özet (AI anahtarı yok — mentor yorumu için GROQ gerekir)"
            return f"{motor_metin}\n\n{kaynak_dipnotu(baglam)}", meta

        # LLM varsa: mentor yorumu (motor iskeleti + VERİ prompt'ta)
        msgs = [{"role": "user", "content": soru}]
        system = _piyasa_ozet_system_prompt(baglam)
        try:
            metin = call_chat(
                messages=msgs,
                system=system,
                max_tokens=1100,
                timeout=timeout,
                _call_fn=_call_fn,
            )
            metin = (metin or "").strip()
            if not metin:
                raise RuntimeError("empty_llm")
            allow = baglam_sembol_allowlist(baglam)
            metin, bad = ticker_grounding(metin, allow)
            meta["grounding_uyari"] = bad
            meta["hint"] = "Mentor yorumu (motordan rakamlar)"
            # #region agent log
            try:
                import time as _t
                with open(
                    "/Users/onurcansever/Desktop/tl-yatirim-asistani/.cursor/debug-715414.log",
                    "a",
                    encoding="utf-8",
                ) as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "715414",
                                "runId": "piyasa-llm-hybrid",
                                "hypothesisId": "H2",
                                "location": "asistan_chat.py:asistan_yanit",
                                "message": "piyasa ozet llm ok",
                                "data": {
                                    "llm_len": len(metin),
                                    "bad_tickers": bad,
                                    "hint": meta["hint"],
                                },
                                "timestamp": int(_t.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                pass
            # #endregion
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
        except Exception as e:
            _log.warning("asistan_yanit piyasa ozet LLM: %s — motor fallback", e)
            meta["hata"] = str(e)
            meta["hint"] = "Motordan özet (AI yanıtı alınamadı — rakamlar yine motordan)"
            # #region agent log
            try:
                import time as _t
                with open(
                    "/Users/onurcansever/Desktop/tl-yatirim-asistani/.cursor/debug-715414.log",
                    "a",
                    encoding="utf-8",
                ) as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "715414",
                                "runId": "piyasa-llm-hybrid",
                                "hypothesisId": "H3",
                                "location": "asistan_chat.py:asistan_yanit",
                                "message": "piyasa ozet llm fallback",
                                "data": {"error": str(e)[:200]},
                                "timestamp": int(_t.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                pass
            # #endregion
            return f"{motor_metin}\n\n{kaynak_dipnotu(baglam)}", meta

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