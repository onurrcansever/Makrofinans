# -*- coding: utf-8 -*-
"""
Reel getiri — Fisher-tam
========================
Nominal getiri ile enflasyondan reel getiriyi hesaplar. Basit çıkarma
(`nominal − enflasyon`) yüksek enflasyonda reel getiriyi **iyimser** okur;
doğru olan Fisher denklemidir:

    reel = (1 + i) / (1 + π) − 1

`macro_anchor_validation` backtesti, basit çıkarmanın 2024 başında (enflasyon
~%65-70) Fisher-tam'dan **ort. ~3 pp, max ~8.8 pp** saptığını gösterdi; bu yüzden
motor genelinde bu yardımcı kullanılır. Not: her iki formül de aynı işarete
sahiptir (reel>0 ⟺ i>π), dolayısıyla "reel pozitif mi" kapıları değişmez;
yalnızca büyüklüğe bağlı eşikler (ör. reel>3pp) daha doğru okunur.
"""
from __future__ import annotations


def reel_getiri(nominal_yuzde: float, enflasyon_yuzde: float) -> float:
    """Fisher-tam reel getiri (yüzde puan). Girdi/çıktı yüzde cinsindendir.

    reel = ((1 + i/100) / (1 + π/100) − 1) × 100
    """
    try:
        payda = 1.0 + float(enflasyon_yuzde) / 100.0
        if payda <= 0:
            return float(nominal_yuzde) - float(enflasyon_yuzde)
        return ((1.0 + float(nominal_yuzde) / 100.0) / payda - 1.0) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return float(nominal_yuzde) - float(enflasyon_yuzde)
