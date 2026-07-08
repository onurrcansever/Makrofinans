# -*- coding: utf-8 -*-
"""TEFAS fon skoru — profil + makro rejime göre seçim yardımı."""
from __future__ import annotations

from typing import List, Optional

from investor_profile import YatirimProfili, vade_kisa_mi, vade_cok_kisa_mi
from tefas_data import FonPerformans, TefasTaramaSonuc
from tefas_universe import KATEGORILER

# Kısa vade (0–6 ay): kategori adı yeterli değil — portföy içeriği de filtrelenir
KISA_VADE_HISSE_ESIK = 15.0
KISA_VADE_FON_SEPETI_ESIK = 20.0
KISA_VADE_KARMA_KATEGORILER = frozenset({"hisse", "degisken", "fon_sepeti"})


def kisa_vade_tefas_uygun(f: FonPerformans) -> bool:
    """
    0–6 ay TEFAS sepeti: para piyasası / borçlanma odaklı.
    YAK gibi borçlanma etiketli ama hisse yoğun fonlar elenir.
    """
    kat = f.kategori or f.etkin_kategori or ""
    if kat in KISA_VADE_KARMA_KATEGORILER:
        return False
    if f.hisse_pct is not None and f.hisse_pct >= KISA_VADE_HISSE_ESIK:
        return False
    if f.dagilim_ozet and "Fon sepeti %" in f.dagilim_ozet:
        try:
            parca = next(p for p in f.dagilim_ozet.split(" · ") if p.startswith("Fon sepeti"))
            pct = float(parca.split("%")[1].split()[0].replace(",", "."))
            if pct >= KISA_VADE_FON_SEPETI_ESIK:
                return False
        except (StopIteration, ValueError, IndexError):
            pass
    return True


def _rejim_kategori_oncelik(rejim: str, risk: str, vade: str = "") -> List[str]:
    if vade_cok_kisa_mi(vade):
        return ["para_piyasasi", "borclanma", "katilim", "serbest_doviz"]
    r = (rejim or "NOTR").upper()
    if r in ("KRIZ", "EM_STRES"):
        return ["para_piyasasi", "borclanma", "serbest_doviz", "altin_emtia"]
    if r == "TL_FIRSAT":
        if risk == "dusuk":
            return ["para_piyasasi", "borclanma", "degisken", "katilim"]
        return ["degisken", "hisse", "borclanma", "fon_sepeti"]
    if r in ("RISK_ON", "NOTR"):
        if risk == "yuksek":
            return ["hisse", "degisken", "fon_sepeti", "serbest_doviz"]
        if risk == "orta":
            return ["degisken", "borclanma", "hisse", "fon_sepeti"]
        return ["para_piyasasi", "borclanma", "degisken", "katilim"]
    if r == "ENFLASYON_KORUMA":
        return ["altin_emtia", "serbest_doviz", "borclanma", "degisken"]
    return ["degisken", "borclanma", "para_piyasasi"]


def _vade_kategori_ceza(profil: YatirimProfili, kategori: str) -> float:
    if vade_cok_kisa_mi(profil.vade):
        if kategori in ("hisse", "degisken", "fon_sepeti"):
            return -40.0
        if kategori == "serbest_doviz":
            return -12.0
        if kategori in ("para_piyasasi", "borclanma", "katilim"):
            return 15.0
    elif vade_kisa_mi(profil.vade):
        if kategori == "hisse":
            return -25.0
        if kategori == "serbest_doviz":
            return -10.0
        if kategori == "para_piyasasi":
            return 8.0
    if profil.vade == "uzun" and kategori == "para_piyasasi":
        return -8.0
    return 0.0


def _getiri_skoru(f: FonPerformans, vade: str) -> float:
    """Vadeye göre ağırlıklı getiri skoru."""
    if vade_cok_kisa_mi(vade) or vade == "kisa_3":
        g = f.getiri_1a
    elif vade_kisa_mi(vade) or vade == "kisa_6":
        g = f.getiri_3a if f.getiri_3a is not None else f.getiri_1a
    else:
        g = f.getiri_ybb if f.getiri_ybb is not None else f.getiri_6a
    if g is None:
        return 0.0
    return max(-15.0, min(25.0, g * 0.8))


def _buyukluk_skoru(f: FonPerformans) -> float:
    if f.fon_buyuklugu is None:
        return 0.0
    if f.fon_buyuklugu >= 5e9:
        return 5.0
    if f.fon_buyuklugu >= 1e9:
        return 3.0
    if f.fon_buyuklugu >= 1e8:
        return 1.0
    return -2.0


def fonlari_skorla(
    sonuc: TefasTaramaSonuc,
    profil: YatirimProfili,
    rejim: str = "NOTR",
    mevduat_reel: Optional[float] = None,
) -> TefasTaramaSonuc:
    oncelik = _rejim_kategori_oncelik(rejim, profil.risk, profil.vade)
    kat_puan = {k: max(0, 12 - i * 3) for i, k in enumerate(oncelik)}

    for f in sonuc.fonlar:
        skor = kat_puan.get(f.kategori, 0.0)
        skor += _vade_kategori_ceza(profil, f.kategori)
        skor += _getiri_skoru(f, profil.vade)
        skor += _buyukluk_skoru(f)

        if mevduat_reel is not None and f.getiri_1a is not None:
            if f.getiri_1a < mevduat_reel and f.kategori in ("para_piyasasi", "borclanma"):
                skor -= 8.0
                f.skor_notu = f"1A getiri %{f.getiri_1a:.1f} — reel mevduat altı"
            elif f.getiri_1a >= mevduat_reel + 2:
                skor += 4.0

        f.skor = round(skor, 1)
        if f.skor >= 18:
            f.oneri = "GUCLU"
        elif f.skor >= 10:
            f.oneri = "UYGUN"
        elif f.skor >= 3:
            f.oneri = "IZLE"
        else:
            f.oneri = "ZAYIF"

        if not f.skor_notu:
            ust = oncelik[0] if oncelik else ""
            if f.dagilim_ozet:
                f.skor_notu = f"İçerik: {f.dagilim_ozet}"
            elif f.kategori == ust:
                f.skor_notu = f"Profil + {rejim} için öncelikli kategori"
            else:
                f.skor_notu = KATEGORILER.get(f.kategori, f.kategori)

    sonuc.fonlar.sort(key=lambda x: (-x.skor, -(x.getiri_3a or -999)))
    return sonuc


def top_oneri(
    sonuc: TefasTaramaSonuc,
    n: int = 5,
    kategori: Optional[str] = None,
    *,
    kategoriler: Optional[tuple] = None,
    kisa_vade: bool = False,
) -> List[FonPerformans]:
    fonlar = sonuc.fonlar
    if kategori and kategori != "tumu":
        fonlar = [f for f in fonlar if f.kategori == kategori]
    elif kategoriler:
        fonlar = [f for f in fonlar if f.kategori in kategoriler]
    if kisa_vade:
        fonlar = [f for f in fonlar if kisa_vade_tefas_uygun(f)]
    return [f for f in fonlar if f.oneri in ("GUCLU", "UYGUN")][:n]
