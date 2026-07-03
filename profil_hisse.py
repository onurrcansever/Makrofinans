# -*- coding: utf-8 -*-
"""
Yatırımcı profili (risk + vade) × hisse/ETF taraması.
Portföy tahsisi ile uyumlu filtreler — tek hisse yerine kısa vadede ETF önceliği vb.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from investor_profile import (
    YatirimProfili,
    profil_degerlendirme,
    vade_cok_kisa_mi,
    vade_kisa_mi,
)


@dataclass
class ProfilHisseSonucu:
    skor_delta: float
    sinyal: str
    profil_notu: str


def profil_firsat_esik(profil: YatirimProfili) -> float:
    """Alım adayı minimum skor — kısa vade / düşük risk daha seçici."""
    if profil.risk == "dusuk" or vade_cok_kisa_mi(profil.vade):
        return 60.0
    if vade_kisa_mi(profil.vade):
        return 58.0
    if profil.risk == "yuksek" and profil.vade == "uzun":
        return 55.0
    return 56.0


def profil_tarama_bilgisi(profil: YatirimProfili, makro_rejim: str) -> Tuple[str, List[str]]:
    notlar = profil_degerlendirme(profil, makro_rejim)
    notlar.append(
        "Hisse taraması profilinize göre ayarlandı: kısa vade → ETF/küresel öncelik; "
        "uzun vade + yüksek risk → büyüme hissesi; düşük risk → defansif/tahvil/altın ETF."
    )
    return profil.ozet(), notlar


def profil_hisse_ayarla(
    sinyal: str,
    skor: float,
    piyasa: str,
    sektor: str,
    varlik_turu: str,
    profil: YatirimProfili,
) -> ProfilHisseSonucu:
    delta = 0.0
    notlar: List[str] = []
    yeni = sinyal
    etf = piyasa == "ETF" or varlik_turu == "etf"
    tek_hisse = not etf

    # ── Risk toleransı ──
    if profil.risk == "dusuk":
        if sektor in ("buyume", "teknoloji") and tek_hisse:
            delta -= 14
            notlar.append("Düşük risk: spekülatif/büyüme hissesi baskılanır")
        if sektor == "gelisen" and etf:
            delta -= 10
            notlar.append("Düşük risk: gelişen piyasa ETF ikincil")
        if sektor in ("tahvil", "altin", "defansif", "temettu") and etf:
            delta += 10
            notlar.append("Düşük risk: koruma/temettü ETF desteklenir")
        if piyasa == "BIST" and tek_hisse:
            delta -= 12
            notlar.append("Düşük risk: BIST tek hisse sınırlı")

    elif profil.risk == "yuksek":
        if sektor in ("buyume", "teknoloji") and tek_hisse:
            delta += 8
            notlar.append("Yüksek risk: büyüme/teknoloji hissesi desteklenir")
        if sektor == "gelisen" and etf:
            delta += 6
            notlar.append("Yüksek risk: gelişen piyasa ETF desteklenir")
        if piyasa == "BIST" and tek_hisse:
            delta += 4
            notlar.append("Yüksek risk: BIST alanı genişletildi")

    # ── Yatırım vadesi ──
    if vade_cok_kisa_mi(profil.vade):
        if tek_hisse:
            delta -= 18
            notlar.append("0–3 ay vade: tek hisse önerilmez — ETF veya nakit tercih")
            if yeni in ("ALIM_FIRSATI", "TREND_ALIM"):
                yeni = "BEKLE"
        if etf and sektor in ("dunya", "abd", "tahvil", "altin"):
            delta += 12
            notlar.append("0–3 ay vade: likit küresel/koruma ETF öncelikli")

    elif profil.vade == "kisa_6" or profil.vade == "kisa":
        if tek_hisse:
            delta -= 10
            notlar.append("Kısa vade: tek hisse ikincil — ETF ile diversifikasyon")
        if piyasa == "BIST" and tek_hisse:
            delta -= 8
            notlar.append("Kısa vade: BIST payı portföy tavanı düşük (%5–8)")
        if etf and sektor in ("dunya", "abd", "tahvil", "altin", "temettu"):
            delta += 8
            notlar.append("Kısa vade: UCITS ETF (VWCE/CSPX) profille uyumlu")

    elif profil.vade == "uzun":
        if tek_hisse and sektor in ("buyume", "teknoloji", "finans", "sanayi"):
            delta += 6
            notlar.append("Uzun vade: kaliteli hisse alımına alan var")
        if etf and sektor in ("dunya", "abd", "teknoloji"):
            delta += 4
            notlar.append("Uzun vade: birikim (Acc) ETF uygun")

    yeni_skor = max(0, min(100, skor + delta))
    esik = profil_firsat_esik(profil)
    if yeni_skor < esik and yeni in ("ALIM_FIRSATI", "TREND_ALIM"):
        yeni = "BEKLE"
        notlar.append(f"Profil sonrası skor <{esik:.0f} — alım kaldırıldı")

    return ProfilHisseSonucu(
        skor_delta=delta,
        sinyal=yeni,
        profil_notu="; ".join(notlar) if notlar else "Profil uyumlu",
    )


def profil_firsat_sinirla(
    firsatlar: list,
    profil: YatirimProfili,
    max_bist: int = 5,
    max_tek_hisse: int = 12,
) -> list:
    """Kısa vade / düşük riskte BIST ve tek hisse aday sayısını sınırla."""
    if not vade_kisa_mi(profil.vade) and profil.risk != "dusuk":
        return firsatlar

    etfler = [h for h in firsatlar if h.piyasa == "ETF"]
    bist = [h for h in firsatlar if h.piyasa == "BIST"]
    abd = [h for h in firsatlar if h.piyasa in ("SP500", "NASDAQ")]

    if vade_cok_kisa_mi(profil.vade):
        return etfler[:10] + abd[:3]

    if vade_kisa_mi(profil.vade):
        return etfler[:8] + abd[:max_tek_hisse - 8] + bist[:max_bist]

    if profil.risk == "dusuk":
        return etfler[:8] + abd[:6] + bist[:2]

    return firsatlar
