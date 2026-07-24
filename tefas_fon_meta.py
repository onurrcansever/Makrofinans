# -*- coding: utf-8 -*-
"""TEFAS/KAP fon gider meta — yıllık yönetim ücreti ve TGO (uydurma oran yok)."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

TEFAS_PROFIL_URL = "https://www.tefas.gov.tr/api/funds/fonProfilBilgiGetir"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_CACHE_TTL_SN = 7 * 24 * 3600
_MIN_REQUEST_GAP = 0.35
_last_req_ts = 0.0


@dataclass
class FonGiderMeta:
    kod: str
    yonetim_ucreti_yillik_pct: Optional[float] = None
    tgo_azami_pct: Optional[float] = None
    tgo_gerceklesen_pct: Optional[float] = None
    kaynak: str = ""
    guncelleme: str = ""
    kap_link: str = ""


def _disk_key(kod: str) -> str:
    return f"tefas_gider:{kod.upper()}"


def _throttle() -> None:
    global _last_req_ts
    wait = _MIN_REQUEST_GAP - (time.time() - _last_req_ts)
    if wait > 0:
        time.sleep(wait)
    _last_req_ts = time.time()


def _http_json(url: str, payload: Optional[dict] = None) -> dict:
    _throttle()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": _UA,
            "Accept": "application/json,*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.tefas.gov.tr",
            "Referer": "https://www.tefas.gov.tr/",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_text(url: str) -> str:
    _throttle()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_tr_float(raw: str) -> Optional[float]:
    s = (raw or "").strip().replace("%", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 0 or v > 100:
        return None
    return v


def _extract_escaped_field(html: str, key: str) -> Optional[float]:
    patterns = (
        rf'\\"{re.escape(key)}\\":\\"([^\\"]*)\\"',
        rf'"{re.escape(key)}":"([^"]*)"',
    )
    for pat in patterns:
        m = re.search(pat, html)
        if m and m.group(1).strip():
            return _parse_tr_float(m.group(1))
    return None


def _extract_label_pct(html: str, label: str) -> Optional[float]:
    m = re.search(re.escape(label), html)
    if not m:
        return None
    window = html[m.end() : m.end() + 900]
    pm = re.search(
        r"%\\u00a0([0-9]+,[0-9]+)|%&nbsp;([0-9]+,[0-9]+)|%\s*([0-9]+,[0-9]+)",
        window,
    )
    if not pm:
        return None
    return _parse_tr_float(pm.group(1) or pm.group(2) or pm.group(3) or "")


def tefas_kap_link(kod: str) -> str:
    """TEFAS profil → KAP fon sayfası linki."""
    try:
        data = _http_json(TEFAS_PROFIL_URL, {"fonKodu": str(kod).upper()})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return ""
    rows = data.get("resultList") or []
    if not rows:
        return ""
    return str(rows[0].get("kapLink") or "").strip()


def _parse_kap_fon_sayfasi(html: str) -> Dict[str, Optional[float]]:
    yon = _extract_escaped_field(html, "uygulananYonetimUcretiOranYillikYuzde")
    if yon is None:
        yon = _extract_escaped_field(html, "ictuzukteYerAlanYonetimUcretiOraniYillikYuzde")
    tgo_kesinti = _extract_escaped_field(html, "fonToplamGiderKesintisiOrani")
    return {
        "yonetim": yon,
        "tgo_kesinti": tgo_kesinti,
    }


def _parse_kap_tgo_bildirim(html: str) -> Dict[str, Optional[float]]:
    return {
        "tgo_azami": _extract_label_pct(html, "Yıllık Azami Fon Toplam Gider Oranı"),
        "tgo_gerceklesen": _extract_label_pct(
            html, "Dönem Sonu İtibariyle Gerçekleşen Fon Toplam Gider Oranı"
        ),
    }


def _bildirim_id_from_kap(html: str) -> Optional[str]:
    """KAP fon sayfasındaki 'Fon Toplam Gider Oranı' bildirimi (varsa)."""
    patterns = (
        # RSC JSON: href sonra aria-label
        r'/tr/Bildirim/(\d+)\\",\\"aria-label\\":\\"Fon Toplam Gider Oranı',
        r'/tr/Bildirim/(\d+)","aria-label":"Fon Toplam Gider Oranı',
        # HTML: aria-label sonra href
        r'aria-label=\\"Fon Toplam Gider Oranı[^\\"]*\\"[^>]{0,240}?/tr/Bildirim/(\d+)',
        r'aria-label="Fon Toplam Gider Oranı[^"]*"[^>]{0,240}?/tr/Bildirim/(\d+)',
        # Eski gevşek eşleşme
        r"Fon Toplam Gider Oranı.{0,240}?/tr/Bildirim/(\d+)",
        r"/tr/Bildirim/(\d+).{0,240}?Fon Toplam Gider Oranı",
    )
    for pat in patterns:
        m = re.search(pat, html, flags=re.S)
        if m:
            return m.group(1)
    return None


def _meta_dolu_mu(meta: FonGiderMeta) -> bool:
    return (
        meta.yonetim_ucreti_yillik_pct is not None
        or meta.tgo_azami_pct is not None
        or meta.tgo_gerceklesen_pct is not None
    )


def fon_gider_meta_cek_tek(kod: str, *, zorla: bool = False) -> FonGiderMeta:
    """Tek fon için KAP/TEFAS gider meta — disk cache ile."""
    kod_u = str(kod).upper().strip()
    meta = FonGiderMeta(kod=kod_u, guncelleme=datetime.now().strftime("%Y-%m-%d %H:%M"))
    if not kod_u:
        return meta

    from disk_onbellek import disk_getir, disk_yaz

    if not zorla:
        cached, _yas = disk_getir(_disk_key(kod_u), _CACHE_TTL_SN, bayat_kabul=False)
        if isinstance(cached, dict) and cached.get("kod") == kod_u:
            hit = FonGiderMeta(
                **{k: cached.get(k) for k in FonGiderMeta.__dataclass_fields__}
            )
            # Boş/başarısız önbelleği 7 gün kilitleme — yeniden dene
            if _meta_dolu_mu(hit):
                return hit

    kaynaklar: List[str] = []
    kap_link = tefas_kap_link(kod_u)
    meta.kap_link = kap_link
    if kap_link:
        kaynaklar.append("TEFAS profil")
        try:
            html = _http_text(kap_link)
            parsed = _parse_kap_fon_sayfasi(html)
            meta.yonetim_ucreti_yillik_pct = parsed.get("yonetim")
            if meta.yonetim_ucreti_yillik_pct is not None:
                kaynaklar.append("KAP fon bilgisi")
            if parsed.get("tgo_kesinti") is not None and meta.tgo_azami_pct is None:
                meta.tgo_azami_pct = parsed["tgo_kesinti"]

            bid = _bildirim_id_from_kap(html)
            if bid:
                try:
                    bhtml = _http_text(f"https://www.kap.org.tr/tr/Bildirim/{bid}")
                    tgo = _parse_kap_tgo_bildirim(bhtml)
                    if tgo.get("tgo_azami") is not None:
                        meta.tgo_azami_pct = tgo["tgo_azami"]
                        kaynaklar.append("KAP TGO bildirimi")
                    if tgo.get("tgo_gerceklesen") is not None:
                        meta.tgo_gerceklesen_pct = tgo["tgo_gerceklesen"]
                except (urllib.error.URLError, TimeoutError, ValueError):
                    pass
            elif meta.yonetim_ucreti_yillik_pct is not None:
                # Yönetim ücreti var, TGO bildirimi KAP’ta yok — uydurma yok
                kaynaklar.append("TGO bildirimi yok")
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass

    meta.kaynak = " · ".join(dict.fromkeys(kaynaklar)) if kaynaklar else ""
    # Yalnızca anlamlı sonuçları uzun TTL ile sakla (boş miss’i kilitleme)
    if _meta_dolu_mu(meta):
        disk_yaz(_disk_key(kod_u), asdict(meta))
    return meta


def fon_gider_meta_cache_oku(
    kodlar: Iterable[str],
    *,
    limit: int = 200,
    bayat_kabul: bool = True,
) -> Dict[str, FonGiderMeta]:
    """Yalnızca disk önbelleği — ağ yok; UI’da anında Yön.%/TGO doldurmak için."""
    from disk_onbellek import disk_getir

    out: Dict[str, FonGiderMeta] = {}
    seen: List[str] = []
    for k in kodlar:
        ku = str(k).upper().strip()
        if not ku or ku in seen:
            continue
        seen.append(ku)
        if len(seen) > max(1, limit):
            break
        cached, _yas = disk_getir(_disk_key(ku), _CACHE_TTL_SN, bayat_kabul=bayat_kabul)
        if isinstance(cached, dict) and cached.get("kod") == ku:
            try:
                out[ku] = FonGiderMeta(
                    **{k: cached.get(k) for k in FonGiderMeta.__dataclass_fields__}
                )
            except TypeError:
                continue
    return out


def fon_gider_meta_cek(
    kodlar: Iterable[str],
    *,
    zorla: bool = False,
    limit: int = 80,
) -> Dict[str, FonGiderMeta]:
    """Birden fazla fon — cache hit hızlı; miss’te rate-limit’li çekim."""
    out: Dict[str, FonGiderMeta] = {}
    seen = []
    for k in kodlar:
        ku = str(k).upper().strip()
        if ku and ku not in seen:
            seen.append(ku)
        if len(seen) >= max(1, limit):
            break
    for ku in seen:
        try:
            out[ku] = fon_gider_meta_cek_tek(ku, zorla=zorla)
        except Exception:
            out[ku] = FonGiderMeta(kod=ku)
    return out


def tgo_gosterim_pct(meta: FonGiderMeta) -> Optional[float]:
    """Tabloda gösterilecek TGO: önce azami yıllık, yoksa dönem gerçekleşen."""
    if meta.tgo_azami_pct is not None:
        return meta.tgo_azami_pct
    return meta.tgo_gerceklesen_pct


def gider_meta_uygula(fonlar: List, meta_map: Dict[str, FonGiderMeta]) -> int:
    """Fon nesnelerine Yön.% / TGO yaz; dolu alan sayısı döner."""
    n = 0
    for f in fonlar:
        m = meta_map.get(str(f.kod).upper()) or meta_map.get(f.kod)
        if not m:
            continue
        if m.yonetim_ucreti_yillik_pct is not None:
            f.yonetim_ucreti_pct = m.yonetim_ucreti_yillik_pct
            n += 1
        tgo = tgo_gosterim_pct(m)
        if tgo is not None:
            f.tgo_pct = tgo
        if m.kaynak:
            f.gider_kaynak = m.kaynak
    return n
