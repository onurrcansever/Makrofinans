# -*- coding: utf-8 -*-
"""
BIST sepet seçimi — AL teyidi (histerezis) + portföydeki mevcut AL pozisyonlarını koruma.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

import config
from investor_profile import YatirimProfili, vade_cok_kisa_mi

STATE_PATH = getattr(config, "TL_ENGINE_STATE_PATH", ".tl_engine_state.json")
BIST_AL_TEYIT = int(os.getenv("BIST_AL_TEYIT", "2"))


def _oku() -> Dict[str, Any]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _yaz(state: Dict[str, Any]) -> None:
    try:
        full = _oku()
        full["bist_sepet"] = state
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _bist_state() -> Dict[str, Any]:
    return dict(_oku().get("bist_sepet") or {})


def _sembol_norm(sembol: str) -> str:
    s = (sembol or "").strip().upper()
    if s and not s.endswith(".IS"):
        s = f"{s}.IS"
    return s


def portfoy_bist_sembolleri(varlik_store) -> Set[str]:
    if not varlik_store:
        return set()
    p = varlik_store.aktif()
    if not p:
        return set()
    return {
        _sembol_norm(poz.sembol)
        for poz in p.pozisyonlar
        if poz.tur == "hisse" and poz.sembol
    }


def _bist_hisseleri(tarama) -> List:
    return [h for h in (tarama.hisseler if tarama else []) if h.piyasa == "BIST"]


def _skor(h) -> float:
    return float(getattr(h, "bilesik_skor", None) or h.skor or 0)


def bist_sepet_sec(
    tarama,
    profil: YatirimProfili,
    bist_w: float,
    varlik_store=None,
) -> Tuple[List, List[str]]:
    """
    Sepet adayları ve açıklayıcı notlar.
    - Yalnızca UYGUN (AL); kısa vadede SINIRLI sepete girmez.
    - Yeni girişler BIST_AL_TEYIT ardışık AL taraması ister.
    - Portföydeki AL sinyalli hisseler korunur (satış önerisi üretilmez).
    """
    notlar: List[str] = []
    if not tarama:
        return [], notlar

    uygun_kodlar = {"UYGUN"}
    if not vade_cok_kisa_mi(profil.vade):
        uygun_kodlar.add("SINIRLI")
    max_n = 1 if (vade_cok_kisa_mi(profil.vade) or bist_w <= 0.05) else 3

    hisseler = _bist_hisseleri(tarama)
    by_sym = {_sembol_norm(h.sembol): h for h in hisseler if h.sembol}

    prev = _bist_state()
    streak: Dict[str, int] = dict(prev.get("al_streak") or {})
    prev_sepet = [_sembol_norm(s) for s in (prev.get("sepet") or [])]

    new_streak: Dict[str, int] = {}
    for h in hisseler:
        sym = _sembol_norm(h.sembol)
        if getattr(h, "alim_uygun", "") == "UYGUN":
            new_streak[sym] = streak.get(sym, 0) + 1
        else:
            new_streak[sym] = 0

    portfoy = portfoy_bist_sembolleri(varlik_store)
    korunan = sorted(
        [by_sym[s] for s in portfoy if s in by_sym and getattr(by_sym[s], "alim_uygun", "") == "UYGUN"],
        key=lambda x: -_skor(x),
    )
    if korunan:
        isimler = ", ".join(h.sembol.replace(".IS", "") for h in korunan)
        notlar.append(
            f"Portföydeki AL sinyalli BIST pozisyonları sepette **korunur** ({isimler})."
        )

    al_adaylar = sorted(
        [h for h in hisseler if getattr(h, "alim_uygun", "") in uygun_kodlar],
        key=lambda x: -_skor(x),
    )
    teyitli = [
        h for h in al_adaylar
        if new_streak.get(_sembol_norm(h.sembol), 0) >= BIST_AL_TEYIT
    ]

    korunan_syms = {_sembol_norm(h.sembol) for h in korunan}
    yeni = [h for h in teyitli if _sembol_norm(h.sembol) not in korunan_syms]

    if korunan:
        sepet = list(korunan)
        for h in yeni:
            if len(sepet) >= max(len(korunan), max_n):
                break
            sepet.append(h)
    else:
        onceki_uygun = [
            by_sym[s] for s in prev_sepet
            if s in by_sym and getattr(by_sym[s], "alim_uygun", "") == "UYGUN"
        ]
        if yeni:
            sepet = yeni[:max_n]
        elif onceki_uygun:
            sepet = sorted(onceki_uygun, key=lambda x: -_skor(x))[:max_n]
            notlar.append(
                f"AL teyidi bekleniyor — önceki sepet korunuyor "
                f"({', '.join(h.sembol.replace('.IS', '') for h in sepet)})."
            )
        elif teyitli:
            sepet = teyitli[:max_n]
        else:
            sepet = al_adaylar[:1] if al_adaylar and BIST_AL_TEYIT <= 1 else []

    if (
        vade_cok_kisa_mi(profil.vade)
        and sepet
        and len(sepet) == 1
        and not korunan
    ):
        notlar.append(
            f"BIST dilimi küçük (%{bist_w * 100:.1f}) — tek AL sinyalli hisse "
            f"({sepet[0].sembol}); çoklu hisse yerine tek pozisyon tercih edilir."
        )

    _yaz({"al_streak": new_streak, "sepet": [_sembol_norm(h.sembol) for h in sepet]})
    return sepet, notlar
