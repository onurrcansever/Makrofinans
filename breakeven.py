# -*- coding: utf-8 -*-
"""
Başa baş EUR/TRY — tek formül, Kapı 3 ve getiri raporu aynı kaynaktan.
"""
from __future__ import annotations

from typing import Optional, Tuple

import config


def breakeven_eur_try(
    eur_spot: float,
    net_tl_yillik: float,
    vade_gun: int,
    eur_mevduat_brut: Optional[float] = None,
) -> float:
    """TL mevduat ile EUR mevduatın EUR cinsinden eşit getirdiği kur (vade sonu)."""
    from yapikredi_rates import net_brut_oran

    eur_brut = eur_mevduat_brut if eur_mevduat_brut is not None else config.EUR_MEVDUAT_YILLIK_FAIZ
    eur_brut_pct = eur_brut * 100 if eur_brut <= 1 else eur_brut
    eur_net = net_brut_oran(eur_brut_pct, vade_gun, "EUR")
    pay = 1 + net_tl_yillik * (vade_gun / 365)
    payda = 1 + eur_net * (vade_gun / 365)
    return eur_spot * pay / payda


def profil_mevduat_parametreleri(
    profil_vade_gun: int,
    tl_brut_fallback: Optional[float] = None,
) -> Tuple[float, int, str]:
    """
    Profil vadesine uygun net TL faizi ve gün sayısı.
    Yapı Kredi tenör günleri (92/181/365) ile Kapı 3 ve mevduat tablosu hizalanır.
    """
    from yapikredi_rates import VADE_GUN, net_brut_oran, yapikredi_tl_faizleri

    ykb = yapikredi_tl_faizleri()
    if ykb:
        if profil_vade_gun <= 95:
            brut, gun = ykb.tl_3ay_brut, VADE_GUN["tl_3ay"]
        elif profil_vade_gun <= 200:
            brut, gun = ykb.tl_6ay_brut, VADE_GUN["tl_6ay"]
        else:
            brut, gun = ykb.tl_1y_brut, VADE_GUN["tl_1y"]
        return net_brut_oran(brut, gun, "TL"), gun, "Yapı Kredi canlı"

    fallback = tl_brut_fallback or config.TL_MEVDUAT_BRUT_FAIZ_VARSAYILAN
    brut_pct = fallback * 100 if fallback <= 1 else fallback
    gun = profil_vade_gun
    if profil_vade_gun <= 95:
        gun = VADE_GUN["tl_3ay"]
    elif profil_vade_gun <= 200:
        gun = VADE_GUN["tl_6ay"]
    else:
        gun = VADE_GUN["tl_1y"]
    return net_brut_oran(brut_pct, gun, "TL"), gun, "varsayılan faiz"
