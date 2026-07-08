# -*- coding: utf-8 -*-
"""Kullanıcı portföy ayarları — para birimi, mevcut pozisyonlar."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MevcutPozisyon:
    tur: str  # tl_mevduat | tefas | nakit_tl | nakit_eur | nakit_usd | diger
    tutar: float
    para_birimi: str = "TL"
    banka: str = ""
    vade_gun: int = 0
    brut_faiz: float = 0.0
    fon_kodu: str = ""
    aciklama: str = ""


@dataclass
class KullaniciPortfoy:
    para_birimi: str = "EUR"  # EUR | TL
    toplam: float = 30000.0
    pozisyonlar: List[MevcutPozisyon] = field(default_factory=list)

    def toplam_eur(self, eur_try: Optional[float] = None) -> float:
        if self.para_birimi == "EUR":
            return self.toplam
        if eur_try and eur_try > 0:
            return self.toplam / eur_try
        return self.toplam / 35.0

    def toplam_tl(self, eur_try: Optional[float] = None) -> float:
        if self.para_birimi == "TL":
            return self.toplam
        eur = self.toplam_eur(eur_try)
        kur = eur_try or 35.0
        return eur * kur

    def mevcut_tl_mevduat(self) -> Optional[MevcutPozisyon]:
        for p in self.pozisyonlar:
            if p.tur == "tl_mevduat" and p.tutar > 0:
                return p
        return None

    def ozet(self) -> str:
        pb = "€" if self.para_birimi == "EUR" else "₺"
        parca = f"{self.toplam:,.0f} {pb}"
        if self.pozisyonlar:
            parca += f" · {len(self.pozisyonlar)} mevcut pozisyon"
        return parca


def varsayilan_portfoy() -> KullaniciPortfoy:
    return KullaniciPortfoy(para_birimi="EUR", toplam=30000.0, pozisyonlar=[])
