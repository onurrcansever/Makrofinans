# -*- coding: utf-8 -*-
"""
4 Kapı histerezisi — CDS çift eşik, haber kriz giriş/çıkış, kalıcı durum.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import config

STATE_PATH = getattr(config, "TL_ENGINE_STATE_PATH", ".tl_engine_state.json")

# CDS histerezis — tablo eşikleri korunur, geri yükseltme gecikmesi eklenir
CDS_DUSURME_ESIK = float(os.getenv("CDS_DUSURME_ESIK", "250"))
CDS_YUKSELTME_ESIK = float(os.getenv("CDS_YUKSELTME_ESIK", "230"))

# Haber kriz histerezisi
HABER_KRIZ_GIRIS = int(os.getenv("HABER_KRIZ_GIRIS", "85"))
HABER_KRIZ_CIKIS = int(os.getenv("HABER_KRIZ_CIKIS", "70"))

KRITIK_VETO_TAVAN = float(os.getenv("KRITIK_VETO_TAVAN", "0.10"))


def _oku() -> Dict[str, Any]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _yaz(state: Dict[str, Any]) -> None:
    state["timestamp"] = datetime.now().isoformat(timespec="seconds")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def state_oku() -> Dict[str, Any]:
    return _oku()


def _cds_tablo_tavan(cds_bp: float) -> float:
    for esik, oran in config.CDS_ESIK_TABLOSU:
        if cds_bp > esik:
            return oran
    return config.CDS_ESIK_TABLOSU[-1][1]


def cds_tavan_histerezis(cds_bp: Optional[float], ham_tavan: float) -> Tuple[float, str]:
    """
    CDS > 250 ile tavan düşer; CDS < 230 olmadan eski yüksek tavan geri gelmez.
    """
    if cds_bp is None:
        return ham_tavan, "CDS verisi yok"

    state = _oku()
    kapilar = state.setdefault("kapı_durumları", {})
    cds_state = kapilar.setdefault("cds", {})
    kilitli = bool(cds_state.get("tavan_kilitli"))
    onceki_kilit_tavan = cds_state.get("kilitli_tavan")

    tablo = _cds_tablo_tavan(cds_bp)

    if cds_bp > CDS_DUSURME_ESIK:
        yeni = min(ham_tavan, tablo)
        cds_state["tavan_kilitli"] = True
        cds_state["kilitli_tavan"] = yeni
        cds_state["son_cds"] = cds_bp
        kapilar["cds"] = cds_state
        state["kapı_durumları"] = kapilar
        _yaz(state)
        return yeni, f"CDS {cds_bp:.0f}bp > {CDS_DUSURME_ESIK:.0f} — tavan kilitlendi %{yeni*100:.0f}"

    if kilitli and cds_bp >= CDS_YUKSELTME_ESIK:
        kilit = float(onceki_kilit_tavan if onceki_kilit_tavan is not None else tablo)
        yeni = min(ham_tavan, kilit, tablo)
        cds_state["son_cds"] = cds_bp
        kapilar["cds"] = cds_state
        state["kapı_durumları"] = kapilar
        _yaz(state)
        return yeni, (
            f"CDS {cds_bp:.0f}bp — histerezis aktif "
            f"(<{CDS_YUKSELTME_ESIK:.0f} olmadan tavan yükselmez)"
        )

    cds_state["tavan_kilitli"] = False
    cds_state.pop("kilitli_tavan", None)
    cds_state["son_cds"] = cds_bp
    kapilar["cds"] = cds_state
    state["kapı_durumları"] = kapilar
    _yaz(state)
    return min(ham_tavan, tablo), f"CDS {cds_bp:.0f}bp — histerezis serbest, tavan tabloya göre"


def haber_kriz_histerezis(etkin_haber: int) -> Tuple[bool, str]:
    """Kriz modu 85'te girer, 70'e düşmeden çıkmaz."""
    state = _oku()
    kapilar = state.setdefault("kapı_durumları", {})
    h = kapilar.setdefault("haber_kriz", {})
    aktif = bool(h.get("aktif"))

    if etkin_haber >= HABER_KRIZ_GIRIS:
        h["aktif"] = True
        h["son_etkin"] = etkin_haber
        kapilar["haber_kriz"] = h
        state["kapı_durumları"] = kapilar
        _yaz(state)
        return True, f"etkin haber {etkin_haber} ≥ {HABER_KRIZ_GIRIS} — kriz kilidi"

    if aktif and etkin_haber >= HABER_KRIZ_CIKIS:
        h["son_etkin"] = etkin_haber
        kapilar["haber_kriz"] = h
        state["kapı_durumları"] = kapilar
        _yaz(state)
        return True, f"etkin haber {etkin_haber} — kriz kilidi (çıkış < {HABER_KRIZ_CIKIS})"

    h["aktif"] = False
    h["son_etkin"] = etkin_haber
    kapilar["haber_kriz"] = h
    state["kapı_durumları"] = kapilar
    _yaz(state)
    return False, f"etkin haber {etkin_haber} — kriz kilidi yok"


def son_tavan_kaydet(tavan: float) -> None:
    state = _oku()
    state["son_tavan"] = tavan
    _yaz(state)


def ppk_faiz_degisim_isaretle(onceki_faiz: Optional[float], yeni_faiz: Optional[float]) -> bool:
    """PPK sonrası faiz değiştiyse rejim teyidini atla bayrağı."""
    if onceki_faiz is None or yeni_faiz is None:
        return False
    if abs(onceki_faiz - yeni_faiz) < 0.01:
        return False
    state = _oku()
    state["rejim_yeniden_degerlendir"] = True
    state["ppk_faiz_onceki"] = onceki_faiz
    state["ppk_faiz_yeni"] = yeni_faiz
    _yaz(state)
    return True


def rejim_yeniden_degerlendir_oku() -> bool:
    return bool(_oku().get("rejim_yeniden_degerlendir"))


def rejim_yeniden_degerlendir_temizle() -> None:
    state = _oku()
    state.pop("rejim_yeniden_degerlendir", None)
    _yaz(state)
