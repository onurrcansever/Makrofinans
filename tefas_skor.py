# -*- coding: utf-8 -*-
"""TEFAS fon skoru — profil + makro rejim; tablo ile aynı PB bazında."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from investor_profile import YatirimProfili, vade_kisa_mi, vade_cok_kisa_mi
from tefas_data import FonPerformans, TefasTaramaSonuc
from tefas_universe import KATEGORILER, tefas_fiyat_kaynak_pb

# Signal Engine v2 karar eşikleri ile aynı skala (0–100)
_ONERI_AL = 66
_ONERI_IZLE = 52
_ONERI_BEKLE = 42
MIN_PEER_FOR_RELATIVE = 8

KISA_VADE_HISSE_ESIK = 15.0
KISA_VADE_FON_SEPETI_ESIK = 20.0
KISA_VADE_KARMA_KATEGORILER = frozenset({"hisse", "degisken", "fon_sepeti"})


def kisa_vade_tefas_uygun(f: FonPerformans) -> bool:
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


def _fon_getiri_kaynak_pb(f: FonPerformans) -> str:
    """Ham fiyat getirisi hangi PB'de — hisse/ETF ile aynı desen."""
    return tefas_fiyat_kaynak_pb(f.para_birimi) or "TL"


def _gosterim_getirileri(
    f: FonPerformans,
    gpb: str,
    eur_s: pd.Series,
    usd_s: pd.Series,
    *,
    gbp_s: Optional[pd.Series] = None,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    from fiyat_para import tablo_getiri

    src = _fon_getiri_kaynak_pb(f)
    bd = usd_s.index if usd_s is not None and not usd_s.empty else None
    g1 = tablo_getiri(
        f.getiri_1a, gpb, 30, eur_s, usd_s, asset_pb=src, gbp_seri=gbp_s, bar_dates=bd,
    )
    g3 = tablo_getiri(
        f.getiri_3a, gpb, 90, eur_s, usd_s, asset_pb=src, gbp_seri=gbp_s, bar_dates=bd,
    )
    gy = tablo_getiri(
        f.getiri_ybb, gpb, 0, eur_s, usd_s, asset_pb=src, gbp_seri=gbp_s, ybb=True, bar_dates=bd,
    )
    return g1, g3, gy


def _getiri_skoru_gosterim(
    f: FonPerformans,
    profil: YatirimProfili,
    gpb: str,
    eur_s: pd.Series,
    usd_s: pd.Series,
    *,
    gbp_s: Optional[pd.Series] = None,
) -> float:
    """Skor — tabloda gösterilen PB ile aynı getiri (fon PB → gosterim)."""
    g1, g3, gy = _gosterim_getirileri(f, gpb, eur_s, usd_s, gbp_s=gbp_s)
    f.getiri_gosterim_1a = g1
    f.getiri_gosterim_3a = g3
    f.getiri_gosterim_ybb = gy
    if vade_cok_kisa_mi(profil.vade) or profil.vade == "kisa_3":
        g = g1 if g1 is not None else f.getiri_1a
    elif vade_kisa_mi(profil.vade) or profil.vade == "kisa_6":
        g = g3 if g3 is not None else g1
    else:
        g = gy if gy is not None else g3
    if g is None:
        return 0.0
    return max(-20.0, min(25.0, float(g) * 0.85))


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


def _net_yillik_pct(oran) -> Optional[float]:
    if oran is None or getattr(oran, "net_yillik", None) is None:
        return None
    v = float(oran.net_yillik)
    return v * 100.0 if v <= 1.0 else v


def _mevduat_1a_esik(
    pb: str,
    mevduat_reel: Optional[float],
    mevduat_ozet: Optional[object],
) -> Optional[float]:
    """1A eşiği — fon PB'sine göre aylık mevduat net (%)."""
    if mevduat_ozet is not None:
        oranlar = getattr(mevduat_ozet, "oranlar", None) or []
        if pb == "USD":
            o = next((x for x in oranlar if str(x.vade).startswith("USD")), None)
            net = _net_yillik_pct(o)
            if net is not None:
                return net / 12.0
        if pb == "EUR":
            eur_net = getattr(mevduat_ozet, "eur_mevduat_net", None)
            if eur_net is not None:
                return float(eur_net) / 12.0
            o = next((x for x in oranlar if str(x.vade).startswith("EUR")), None)
            net = _net_yillik_pct(o)
            if net is not None:
                return net / 12.0
        if pb == "TL":
            profil_net = getattr(mevduat_ozet, "profil_vade_net", None)
            if profil_net is not None:
                return float(profil_net) / 12.0
    if pb == "TL" and mevduat_reel is not None:
        # Geriye uyum: yıllık reel vs 1A (eski davranış)
        return float(mevduat_reel)
    return None


def _mevduat_ayari(
    f: FonPerformans,
    *,
    mevduat_reel: Optional[float],
    mevduat_ozet: Optional[object],
) -> Tuple[float, str]:
    """
    Mevduat cezası/ikramiyesi.
    Karşılaştırma: ham fiyat getirisi (fon PB) vs o PB'nin mevduat 1A eşiği.
    +4 ikramiye yalnızca TL fonlara (USD/EUR fonlarda kur/alfa şişmesini önler).
    """
    pb = _fon_getiri_kaynak_pb(f)
    esik = _mevduat_1a_esik(pb, mevduat_reel, mevduat_ozet)
    if esik is None or f.getiri_1a is None:
        return 0.0, ""
    g = float(f.getiri_1a)
    if g < esik and f.kategori in ("para_piyasasi", "borclanma"):
        return -8.0, (
            f"1A getiri %{g:.1f} ({pb}) — {pb} mevduat eşiği %{esik:.2f} altı"
        )
    # İkramiye: sadece TL — USD fon + TL eşiği avantajını kapat
    if pb == "TL" and g >= esik + 2:
        return 4.0, ""
    return 0.0, ""


def _ham_to_abs_norm(ham: float) -> float:
    return max(0.0, min(99.0, (ham + 5.0) / 50.0 * 100.0))


def _kategori_sayilari(fonlar: Sequence[FonPerformans]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for f in fonlar:
        k = f.kategori or ""
        out[k] = out.get(k, 0) + 1
    return out


def _tum_getiriler_negatif(f: FonPerformans) -> bool:
    vals = [f.getiri_gosterim_1a, f.getiri_gosterim_3a, f.getiri_gosterim_ybb]
    present = [v for v in vals if v is not None]
    if len(present) < 2:
        return False
    return all(v <= 0 for v in present)


def _oneri_from_norm(norm: float) -> str:
    if norm >= _ONERI_AL:
        return "AL"
    if norm >= _ONERI_IZLE:
        return "IZLE"
    if norm >= _ONERI_BEKLE:
        return "BEKLE"
    return "ZAYIF"


def _skor_ve_oneri_uygula(
    f: FonPerformans,
    *,
    kategori_sayilari: Dict[str, int],
) -> None:
    kat_n = kategori_sayilari.get(f.kategori or "", 0)
    f.akran_kucuk = kat_n < MIN_PEER_FOR_RELATIVE
    norm = _ham_to_abs_norm(f.skor_ham)

    if _tum_getiriler_negatif(f):
        norm = min(norm, float(_ONERI_IZLE - 1))

    if norm >= 100.0 or (norm >= 99.5 and f.skor_ham < 40):
        norm = 99.0
    if (
        norm >= 99.0
        and f.getiri_gosterim_ybb is not None
        and f.getiri_gosterim_ybb > 2.0
        and (f.getiri_gosterim_1a or 0) > 0
    ):
        norm = 100.0

    f.skor = round(norm, 1)
    f.oneri = _oneri_from_norm(f.skor)

    if f.oneri == "AL" and _tum_getiriler_negatif(f):
        f.oneri = "BEKLE"
        f.skor = min(f.skor, float(_ONERI_BEKLE + 3))
        f.skor_notu = (f.skor_notu + " · Görünen getiriler negatif").strip(" ·")


def tefas_oneri_yenile(
    fonlar: Sequence[FonPerformans],
    *,
    tum_fonlar: Optional[Sequence[FonPerformans]] = None,
) -> None:
    """Etiketleri mutlak skorla yenile — filtrelenmiş küçük gruplarda yüzdelik sıralama yok."""
    if not fonlar:
        return
    ref = tum_fonlar if tum_fonlar is not None else fonlar
    kat_s = _kategori_sayilari(ref)
    for f in fonlar:
        _skor_ve_oneri_uygula(f, kategori_sayilari=kat_s)


def assert_tefas_skor_tutarliligi(fonlar: Sequence[FonPerformans]) -> None:
    """CI: AL + skor 100 + tüm görünen getiriler negatif olamaz."""
    for f in fonlar:
        if f.skor >= 100.0 and f.oneri == "AL":
            raise AssertionError(
                f"{f.kod}: skor 100 + AL — doyum/küçük akran hatası (ham={f.skor_ham})"
            )
        if f.oneri == "AL" and _tum_getiriler_negatif(f):
            raise AssertionError(
                f"{f.kod}: AL while all display returns negative "
                f"(1A={f.getiri_gosterim_1a}, 3A={f.getiri_gosterim_3a}, YBB={f.getiri_gosterim_ybb})"
            )


def fonlari_skorla(
    sonuc: TefasTaramaSonuc,
    profil: YatirimProfili,
    rejim: str = "NOTR",
    mevduat_reel: Optional[float] = None,
    *,
    gosterim_pb: str = "EUR",
    eur_seri: Optional[pd.Series] = None,
    usd_seri: Optional[pd.Series] = None,
    gbp_seri: Optional[pd.Series] = None,
    mevduat_ozet: Optional[object] = None,
) -> TefasTaramaSonuc:
    from fiyat_para import fx_serileri_al

    gpb = gosterim_pb or "EUR"
    eur_s, usd_s, gbp_s = eur_seri, usd_seri, gbp_seri
    if (
        eur_s is None or usd_s is None
        or getattr(eur_s, "empty", True)
        or getattr(usd_s, "empty", True)
    ):
        eur_s, usd_s, gbp_loaded, _ = fx_serileri_al()
        if gbp_s is None:
            gbp_s = gbp_loaded
    if getattr(eur_s, "empty", True) or getattr(usd_s, "empty", True):
        gpb = "TL"

    oncelik = _rejim_kategori_oncelik(rejim, profil.risk, profil.vade)
    kat_puan = {k: max(0, 12 - i * 3) for i, k in enumerate(oncelik)}
    kat_s = _kategori_sayilari(sonuc.fonlar)

    for f in sonuc.fonlar:
        f.skor_pb = gpb
        kat = kat_puan.get(f.kategori, 0.0)
        vade = _vade_kategori_ceza(profil, f.kategori)
        getiri = _getiri_skoru_gosterim(f, profil, gpb, eur_s, usd_s, gbp_s=gbp_s)
        buyuk = _buyukluk_skoru(f)
        mevduat_adj, mev_not = _mevduat_ayari(
            f, mevduat_reel=mevduat_reel, mevduat_ozet=mevduat_ozet,
        )
        if mev_not:
            f.skor_notu = mev_not

        skor = kat + vade + getiri + buyuk + mevduat_adj
        f.skor_ham = round(skor, 1)
        src_pb = _fon_getiri_kaynak_pb(f)
        f.skor_faktorler = {
            "kategori": round(kat, 1),
            "vade_uyum": round(vade, 1),
            f"getiri_{gpb}": round(getiri, 1),
            "buyukluk": round(buyuk, 1),
            "mevduat": round(mevduat_adj, 1),
        }

        if not f.skor_notu:
            ust = oncelik[0] if oncelik else ""
            if f.dagilim_ozet:
                f.skor_notu = f"İçerik: {f.dagilim_ozet} · getiri kaynak {src_pb}"
            elif f.kategori == ust:
                f.skor_notu = f"Profil + {rejim} için öncelikli kategori · getiri kaynak {src_pb}"
            else:
                f.skor_notu = f"{KATEGORILER.get(f.kategori, f.kategori)} · getiri kaynak {src_pb}"

        _skor_ve_oneri_uygula(f, kategori_sayilari=kat_s)

    sonuc.fonlar.sort(key=lambda x: (-x.skor, -(x.getiri_gosterim_3a or x.getiri_3a or -999)))
    return sonuc


def tefas_skorlu_kopya(
    ham,
    profil,
    rejim: str = "NOTR",
    mevduat_reel: Optional[float] = None,
    **kwargs,
):
    """Ham TEFAS verisini skorla (önbelleği bozmamak için deepcopy)."""
    from copy import deepcopy

    from app_veri import tefas_yukleniyor

    if not ham or tefas_yukleniyor(ham) or getattr(ham, "hata", ""):
        return None
    sonuc = deepcopy(ham)
    return fonlari_skorla(
        sonuc, profil, rejim=rejim, mevduat_reel=mevduat_reel, **kwargs,
    )


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
    return [f for f in fonlar if f.oneri in ("AL", "IZLE")][:n]
