# -*- coding: utf-8 -*-
"""TÜFE yıllık enflasyon — EVDS çoklu seri + manual_inputs + tazelik kontrolü."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import List, Optional, Tuple

MANUAL_PATH = os.path.join(os.path.dirname(__file__), "manual_inputs.json")
RESMI_PATH = os.path.join(os.path.dirname(__file__), "enflasyon_resmi.json")

# EVDS'te J01 (2003=100) ve J0 (2003=100 farklı taban) — en güncel ayı seç
_EVDS_ENDEKS_SERILERI = ("TP.FG.J01", "TP.FG.J0")


def _ay_parcala(tarih: str) -> tuple[int, int]:
    y, m = tarih.split("-", 1)
    return int(y), int(m)


def _ay_tuple(tarih: str) -> tuple[int, int]:
    return _ay_parcala(tarih)


def _ay_fark_aylik(son_ay: str, bugun: Optional[datetime] = None) -> int:
    """Son veri ayı ile bugün arasındaki ay farkı (0 = aynı ay)."""
    bugun = bugun or datetime.now()
    y, m = _ay_parcala(son_ay)
    return (bugun.year - y) * 12 + (bugun.month - m)


def enflasyon_manuel_son() -> Optional[Tuple[float, str, str]]:
    """
    Öncelik: enflasyon_resmi.json (sync ile gelir, CDS dokunmaz) → manual_inputs.json.
    Alanlar: enflasyon_tr_yillik, enflasyon_ay (ör. 2026-6).
    """
    for path, etiket in ((RESMI_PATH, "enflasyon_resmi.json"), (MANUAL_PATH, "manual_inputs.json")):
        try:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            val = d.get("enflasyon_tr_yillik")
            if val is None:
                continue
            ay = str(d.get("enflasyon_ay") or d.get("enflasyon_tarih") or d.get("guncelleme_tarihi") or "")
            if ay and len(ay) >= 7 and ay[4] == "-":
                if len(ay) == 10:
                    dt = datetime.strptime(ay[:10], "%Y-%m-%d")
                    ay_etiket = f"{dt.year}-{dt.month}"
                else:
                    ay_etiket = ay[:7]
            elif ay and len(ay) >= 7:
                ay_etiket = ay[:7]
            else:
                ay_etiket = ay or "manual"
            notu = d.get("enflasyon_guncelleme_notu") or d.get("kaynak") or etiket
            return float(val), f"TÜİK/resmi — {notu} ({ay_etiket})", ay_etiket
        except Exception:
            continue
    return None


def _evds_seri_yoy(api_key: str, seri: str) -> Optional[Tuple[float, str, str]]:
    import data_sources as ds

    items = ds._evds_get(seri, api_key, gun_sayisi=900)
    if not items:
        return None
    field = ds._evds_field_key(seri)
    by_date: dict[str, float] = {}
    for it in items:
        v = it.get(field)
        if v not in (None, "", "None"):
            by_date[it["Tarih"]] = float(str(v).replace(",", "."))
    if len(by_date) < 13:
        return None
    son_tarih = max(by_date.keys(), key=_ay_tuple)
    y, m = _ay_parcala(son_tarih)
    onceki = f"{y - 1}-{m}"
    if onceki not in by_date:
        return None
    yoy = (by_date[son_tarih] / by_date[onceki] - 1) * 100
    return yoy, f"TÜFE yıllık {son_tarih} ({seri} endeks YoY)", son_tarih


def enflasyon_evds_son(api_key: str) -> Optional[Tuple[float, str, str]]:
    """EVDS'ten en güncel aylık TÜFE YoY."""
    if not api_key:
        return None
    adaylar: List[Tuple[float, str, str]] = []
    for seri in _EVDS_ENDEKS_SERILERI:
        try:
            sonuc = _evds_seri_yoy(api_key, seri)
            if sonuc:
                adaylar.append(sonuc)
        except Exception:
            continue
    if not adaylar:
        return None
    return max(adaylar, key=lambda x: _ay_tuple(x[2]))


# ─────────────────────────────────────────────────────────────────────────
# Aylık TÜFE endeks serisi — reel getiri / enflasyona endeksli çizgi için
# ─────────────────────────────────────────────────────────────────────────
_TUFE_ENDEKS_SERI = "TP.FG.J01"  # TÜFE (2003=100), aylık
_TUFE_ENDEKS_TTL = 24 * 3600  # 1 gün
_TUFE_ENDEKS_ANAHTAR = "tufe_endeks_j01"


def _ay_key(tarih: str) -> str:
    """EVDS 'YYYY-M' → normalize 'YYYY-MM'."""
    y, m = _ay_parcala(tarih)
    return f"{y:04d}-{m:02d}"


def _tufe_evds_uret() -> Optional[dict]:
    """EVDS'ten aylık TÜFE endeksi: {'YYYY-MM': endeks}. Anahtar/veri yoksa None."""
    try:
        import config
        import data_sources as ds
    except Exception:
        return None
    api_key = getattr(config, "EVDS_API_KEY", "")
    if not api_key:
        return None
    items = ds._evds_get(_TUFE_ENDEKS_SERI, api_key, gun_sayisi=1200)  # ~3+ yıl
    if not items:
        return None
    field = ds._evds_field_key(_TUFE_ENDEKS_SERI)
    out: dict[str, float] = {}
    for it in items:
        v = it.get(field)
        tarih = it.get("Tarih")
        if v in (None, "", "None") or not tarih:
            continue
        try:
            out[_ay_key(tarih)] = float(str(v).replace(",", "."))
        except (ValueError, IndexError):
            continue
    return out or None


def _sentetik_endeks(baslangic_iso: str, bitis_iso: str) -> dict:
    """EVDS yoksa: yıllık TÜFE oranından sabit aylık bileşikle sentetik endeks.
    Mutlak taban önemsiz — çizgi CPI(t)/CPI(d) oranı kullanır."""
    res = enflasyon_manuel_son()
    if not res:
        return {}
    yillik = res[0]
    if yillik is None or yillik <= -100:
        return {}
    aylik = (1.0 + yillik / 100.0) ** (1.0 / 12.0)
    try:
        by, bm = int(baslangic_iso[:4]), int(baslangic_iso[5:7])
        ey, em = int(bitis_iso[:4]), int(bitis_iso[5:7])
    except (ValueError, IndexError):
        return {}
    out: dict[str, float] = {}
    idx = 100.0
    y, m = by, bm
    while (y, m) <= (ey, em):
        out[f"{y:04d}-{m:02d}"] = idx
        idx *= aylik
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def tufe_endeks_serisi(baslangic_iso: str, bitis_iso: str) -> Tuple[dict, str]:
    """Aylık TÜFE endeksi ({'YYYY-MM': endeks}) ve kaynak etiketi döner.

    EVDS anahtarı varsa gerçek TÜİK endeksi (disk-önbellekli, ağ bekletmez);
    yoksa `enflasyon_resmi.json` yıllık oranından sentetik endeks üretir."""
    try:
        import disk_onbellek

        veri = disk_onbellek.disk_getir_aninda(
            _TUFE_ENDEKS_ANAHTAR, _TUFE_ENDEKS_TTL, _tufe_evds_uret, varsayilan=None
        )
    except Exception:
        veri = _tufe_evds_uret()
    if veri:
        return veri, "TÜİK/EVDS (TP.FG.J01 aylık endeks)"
    return _sentetik_endeks(baslangic_iso, bitis_iso), "yaklaşık (yıllık orandan)"


def _ay_ilk_gun(ay_key: str) -> date:
    return date(int(ay_key[:4]), int(ay_key[5:7]), 1)


def cpi_gun_gunluk(
    seri: dict, tarih_iso: str, yillik_oran: Optional[float] = None
) -> Optional[float]:
    """Aylık TÜFE endeksinden **günlük** çözünürlükte CPI.

    Aylar arası geometrik ara değer; son ayın ötesindeki günler için son
    aylık büyümeyle (yoksa `yillik_oran`la) günlük sürükleme. Bu sayede tek ay
    içinde bile enflasyon farkı birikir (aylık endeksin düz basamağı yerine)."""
    if not seri:
        return None
    try:
        t = date(int(tarih_iso[:4]), int(tarih_iso[5:7]), int(tarih_iso[8:10]))
    except (ValueError, IndexError):
        return None
    keys = sorted(seri.keys())
    anchors = [(_ay_ilk_gun(k), seri[k]) for k in keys]
    if t <= anchors[0][0]:
        return anchors[0][1]
    for (d0, v0), (d1, v1) in zip(anchors, anchors[1:]):
        if d0 <= t <= d1:
            span = (d1 - d0).days
            if span <= 0 or v0 <= 0:
                return v0
            f = (t - d0).days / span
            return v0 * (v1 / v0) ** f
    # Son çapanın ötesi → günlük sürüklemeyle uzat
    dL, vL = anchors[-1]
    gunluk = 1.0
    if len(anchors) >= 2 and anchors[-2][1] > 0:
        dP, vP = anchors[-2]
        gun = (dL - dP).days or 30
        gunluk = (vL / vP) ** (1.0 / gun)
    elif yillik_oran:
        gunluk = (1.0 + yillik_oran / 100.0) ** (1.0 / 365.0)
    return vL * gunluk ** ((t - dL).days)


def enflasyon_ref_serisi(
    tarihler: List[str],
    maliyetler: List[float],
    seri_cpi: dict,
    yillik_oran: Optional[float] = None,
) -> List[float]:
    """Enflasyona endeksli maliyet serisi.

    ref(t) = Σ_{d≤t} Δmaliyet(d) × CPI(t)/CPI(d) = CPI(t) · Σ Δmaliyet(d)/CPI(d).
    CPI günlük çözünürlükte (`cpi_gun_gunluk`) alınır; böylece tek ay içinde bile
    enflasyon farkı görünür. `maliyetler` içindeki NaN günler atlanır; ilk katkıdan
    önceki günler NaN döner. Sabit endekste ref == maliyet; %100 enflasyonda tek
    katkı iki katına çıkar."""
    ref_vals: List[float] = []
    onceki_mal = 0.0
    birikim = 0.0
    basladi = False
    for i, t in enumerate(tarihler):
        mv = maliyetler[i]
        c_t = cpi_gun_gunluk(seri_cpi, t, yillik_oran)
        if mv == mv and c_t:  # NaN değil
            birikim += (mv - onceki_mal) / c_t
            onceki_mal = mv
            basladi = True
        ref_vals.append(birikim * c_t if (c_t and basladi) else float("nan"))
    return ref_vals


def cpi_gun(seri: dict, tarih_iso: str) -> Optional[float]:
    """Verilen güne ait TÜFE endeksi — o ayın (≤) en yakın verisini döner (basamak)."""
    if not seri:
        return None
    try:
        hedef = f"{int(tarih_iso[:4]):04d}-{int(tarih_iso[5:7]):02d}"
    except (ValueError, IndexError):
        return None
    keys = sorted(seri.keys())
    uygun = [k for k in keys if k <= hedef]
    if uygun:
        return seri[uygun[-1]]
    return seri[keys[0]]  # hedef tüm seriden önceyse en erken endeksi kullan


def enflasyon_resmi_al(
    api_key: str = "",
    *,
    max_ay_gecikme: int = 1,
) -> Tuple[Optional[float], str, List[str]]:
    """
    En güncel resmi/ yarı-resmi enflasyon.
    Returns: (deger, kaynak_metni, uyarilar)
    """
    uyarilar: List[str] = []
    evds = enflasyon_evds_son(api_key) if api_key else None
    manuel = enflasyon_manuel_son()

    secilen: Optional[Tuple[float, str, str]] = None
    if evds and manuel:
        secilen = manuel if _ay_tuple(manuel[2]) >= _ay_tuple(evds[2]) else evds
    elif manuel:
        secilen = manuel
    elif evds:
        secilen = evds

    if not secilen:
        return None, "EVDS/TÜİK verisi yok", uyarilar

    deger, kaynak, son_ay = secilen
    gecikme = _ay_fark_aylik(son_ay)
    if gecikme > max_ay_gecikme:
        uyarilar.append(
            f"TÜFE verisi **{son_ay}** ayına ait ({gecikme} ay gecikmeli). "
            f"Reel getiri hesapları güncel TÜİK bülteniyle sapabilir — "
            f"manual_inputs.json içine `enflasyon_tr_yillik` + `enflasyon_ay` ekleyin."
        )
        kaynak = f"{kaynak} · ⚠ {gecikme} ay gecikmeli"
    elif "EVDS" in kaynak or "endeks" in kaynak:
        kaynak = f"TCMB EVDS — {kaynak} (TÜİK, resmi)"

    return deger, kaynak, uyarilar
