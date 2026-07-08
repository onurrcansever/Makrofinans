# -*- coding: utf-8 -*-
"""
PPK / FOMC takvim farkındalığı — yeni TL girişi erteleme notu, faiz değişimi bayrağı.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

import config
from gate_hysteresis import ppk_faiz_degisim_isaretle, state_oku


@dataclass
class PpkFomcDurumu:
    ppk_tarih: Optional[date]
    ppk_gun: Optional[int]
    ppk_bekle: bool
    ppk_notu: str
    fomc_tarih: Optional[date]
    fomc_gun: Optional[int]
    fomc_notu: str


def _sonraki(takvim: List[date]) -> Tuple[Optional[date], Optional[int]]:
    bugun = date.today()
    gelecek = [d for d in takvim if d >= bugun]
    if not gelecek:
        return None, None
    sonraki = min(gelecek)
    return sonraki, (sonraki - bugun).days


def ppk_fomc_durumu(bugun: Optional[date] = None) -> PpkFomcDurumu:
    bugun = bugun or date.today()
    ppk_takvim = list(getattr(config, "TCMB_PPK_TAKVIM", []))
    fomc_takvim = list(getattr(config, "FOMC_TAKVIM", []))

    ppk_t, ppk_g = _sonraki(ppk_takvim)
    fomc_t, fomc_g = _sonraki(fomc_takvim)

    esik = int(getattr(config, "PPK_BEKLE_GUN", 7))
    ppk_bekle = ppk_g is not None and ppk_g <= esik
    ppk_notu = ""
    if ppk_bekle and ppk_t:
        ppk_notu = (
            f"[BİLGİ] PPK {ppk_t.strftime('%d.%m.%Y')}'te ({ppk_g} gün): "
            f"yeni TL girişini karar sonrasına ertelemek makul."
        )

    fomc_notu = ""
    if fomc_t and fomc_g is not None:
        fomc_notu = (
            f"Sonraki FOMC: {fomc_t.strftime('%d.%m.%Y')} ({fomc_g} gün)."
        )

    return PpkFomcDurumu(
        ppk_tarih=ppk_t,
        ppk_gun=ppk_g,
        ppk_bekle=ppk_bekle,
        ppk_notu=ppk_notu,
        fomc_tarih=fomc_t,
        fomc_gun=fomc_g,
        fomc_notu=fomc_notu,
    )


def ppk_faiz_takip(onceki: Optional[float], yeni: Optional[float]) -> bool:
    """PPK sonrası faiz değiştiyse state'e rejim yeniden değerlendir bayrağı."""
    return ppk_faiz_degisim_isaretle(onceki, yeni)


def ppk_teyit_atla() -> bool:
    return bool(state_oku().get("rejim_yeniden_degerlendir"))
