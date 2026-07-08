# -*- coding: utf-8 -*-
"""TÜFE yıllık enflasyon — EVDS çoklu seri + manual_inputs + tazelik kontrolü."""
from __future__ import annotations

import json
import os
from datetime import datetime
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
