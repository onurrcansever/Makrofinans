# -*- coding: utf-8 -*-
"""
BIST sepet seçimi — Karar=AL (UYGUN) olan hisselerden skor sırasıyla seçim.
Portföy Tahsisi Varlıklarım'dan bağımsızdır; mevcut pozisyonlar öneriyi etkilemez.
"""
from __future__ import annotations

from typing import List, Tuple

from investor_profile import YatirimProfili, vade_cok_kisa_mi


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
    Bugün Karar=AL (UYGUN) olan BIST hisselerinden portföy sepeti.
    varlik_store yok sayılır — öneri yalnızca tarama skoruna göre.
    """
    del varlik_store
    notlar: List[str] = []
    if not tarama:
        return [], notlar

    max_n = 1 if (vade_cok_kisa_mi(profil.vade) or bist_w <= 0.05) else 3

    hisseler = _bist_hisseleri(tarama)
    al_adaylar = sorted(
        [h for h in hisseler if getattr(h, "alim_uygun", "") == "UYGUN"],
        key=lambda x: -_skor(x),
    )

    if not al_adaylar:
        notlar.append(
            "Bugün trend/momentum filtresine uyan **AL** BIST adayı yok — "
            "teknik teyit + SMA200 üstü + makul 52H seviyesi gerekir."
        )

    sepet = al_adaylar[:max_n]

    if (
        vade_cok_kisa_mi(profil.vade)
        and len(sepet) == 1
        and sepet
    ):
        notlar.append(
            f"Kısa vade — BIST diliminde tek hisse önerisi: **{sepet[0].sembol.replace('.IS', '')}**."
        )

    return sepet, notlar
