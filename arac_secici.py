# -*- coding: utf-8 -*-
"""Makro dilim içinde araç seçimi — mevduat vs TEFAS vs fiziki/ETF (net_proxy).

Getiriler brüt kalır; stopaj/TGO/makas yalnızca karşılaştırma sürüklemesi.
Banka/TEFAS ekranı nihai vergi kaynağıdır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config
from tefas_stopaj import VARSAYILAN_DONEM, tefas_stopaj_sinifi


@dataclass
class AracAday:
    tur: str  # mevduat | tefas | fiziki | etf
    ad: str
    net_proxy: float
    beklenen_getiri_pct: float = 0.0
    maliyet_pct: float = 0.0
    maliyet_kalemleri: Dict[str, float] = field(default_factory=dict)
    etiket: str = ""
    kod: str = ""


@dataclass
class DilimKarari:
    dilim: str  # tl_deposit | eur_cash | usd_cash | gold
    kazanan: AracAday
    yedek: Optional[AracAday] = None
    gerekce: str = ""
    dilim_pay: float = 0.0  # makro sınıf içinden kesilecek oran (0–1)
    notlar: List[str] = field(default_factory=list)


def maliyet_suruklenmesi_yillik(
    *,
    tgo_pct: float = 0.0,
    stopaj_orani_pct: float = 0.0,
    beklenen_getiri_pct: float = 0.0,
    makas_pct: float = 0.0,
    ter_pct: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """Yıllık maliyet sürüklemesi (yüzde puan) + kalemler."""
    stopaj_suruk = max(float(beklenen_getiri_pct), 0.0) * (
        float(stopaj_orani_pct) / 100.0
    )
    kalemler = {
        "tgo": float(tgo_pct or 0.0),
        "ter": float(ter_pct or 0.0),
        "makas": float(makas_pct or 0.0),
        "stopaj_suruk": stopaj_suruk,
    }
    return sum(kalemler.values()), kalemler


def _fon_beklenen_getiri(fon: Any, *, kisa_vade: bool) -> float:
    """Brüt getiri proxy — kısa vadede 3A→yıllık; uzun vadede YBB veya 3A×4."""
    g3 = getattr(fon, "getiri_3a", None)
    gy = getattr(fon, "getiri_ybb", None)
    if kisa_vade:
        if g3 is not None:
            return float(g3) * 4.0
        if gy is not None:
            return float(gy)
        return 0.0
    if gy is not None:
        return float(gy)
    if g3 is not None:
        return float(g3) * 4.0
    return 0.0


def _usd_mevduat_net(mevduat_ozet: Any) -> float:
    if mevduat_ozet is None:
        return float(getattr(config, "USD_MEVDUAT_YILLIK_FAIZ", 0.015)) * 75.0
    for o in getattr(mevduat_ozet, "oranlar", []) or []:
        if getattr(o, "vade", "") == "USD mevduat":
            return float(o.net_yillik) * 100.0
    return 1.0


def _fon_aday(
    fon: Any,
    *,
    kisa_vade: bool,
    iktisap_donemi: str,
    tgo_pct: Optional[float] = None,
    yonetim_pct: Optional[float] = None,
) -> AracAday:
    beklenen = _fon_beklenen_getiri(fon, kisa_vade=kisa_vade)
    _, stopaj_pct, _ = tefas_stopaj_sinifi(
        ad=getattr(fon, "ad", "") or "",
        kategori=getattr(fon, "kategori", "") or "",
        hisse_pct=getattr(fon, "hisse_pct", None),
        iktisap_donemi=iktisap_donemi,
    )
    tgo = float(tgo_pct) if tgo_pct is not None else float(
        getattr(fon, "tgo_pct", None) or 0.0
    )
    if tgo <= 0 and yonetim_pct is not None:
        tgo = float(yonetim_pct)
    maliyet, kalemler = maliyet_suruklenmesi_yillik(
        tgo_pct=tgo,
        stopaj_orani_pct=stopaj_pct,
        beklenen_getiri_pct=beklenen,
    )
    return AracAday(
        tur="tefas",
        ad=getattr(fon, "kisa_ad", None) or getattr(fon, "kod", "fon"),
        kod=getattr(fon, "kod", "") or "",
        net_proxy=beklenen - maliyet,
        beklenen_getiri_pct=beklenen,
        maliyet_pct=maliyet,
        maliyet_kalemleri=kalemler,
        etiket=getattr(fon, "oneri", "") or "",
    )


def _kazanan_sec(
    adaylar: Sequence[AracAday],
    *,
    min_fark: float,
    tercih_tur: Optional[str] = None,
) -> Tuple[AracAday, Optional[AracAday], str]:
    sirali = sorted(adaylar, key=lambda a: a.net_proxy, reverse=True)
    if not sirali:
        raise ValueError("aday yok")
    bir = sirali[0]
    iki = sirali[1] if len(sirali) > 1 else None
    if iki is None:
        return bir, None, f"{bir.ad} tek aday (net ~%{bir.net_proxy:.1f})"
    fark = bir.net_proxy - iki.net_proxy
    if tercih_tur and abs(fark) < min_fark:
        tercih = next((a for a in sirali if a.tur == tercih_tur), None)
        if tercih is not None:
            yedek = next((a for a in sirali if a is not tercih), None)
            return (
                tercih,
                yedek,
                f"Fark <%{min_fark:.1f} pp — temkin: {tercih.ad} "
                f"(net ~%{tercih.net_proxy:.1f})",
            )
    return (
        bir,
        iki,
        f"{bir.ad} önde (net ~%{bir.net_proxy:.1f} vs {iki.ad} ~%{iki.net_proxy:.1f})",
    )


def dilim_karari_tl(
    *,
    tl_w: float,
    mevduat_ozet: Any = None,
    fon_adaylari: Optional[Sequence[Any]] = None,
    kisa_vade: bool = False,
    iktisap_donemi: Optional[str] = None,
) -> Optional[DilimKarari]:
    if tl_w < 0.005:
        return None
    donem = iktisap_donemi or getattr(
        config, "TEFAS_STOPAJ_VARSAYILAN_DONEM", VARSAYILAN_DONEM
    )
    min_fark = float(getattr(config, "ARAC_MIN_FARK_PCT", 0.5))
    max_pay = float(getattr(config, "TEFAS_DILIM_PAY", 0.35))

    tl_net = float(getattr(mevduat_ozet, "profil_vade_net", 0) or 0) if mevduat_ozet else 0.0
    adaylar: List[AracAday] = [
        AracAday(
            tur="mevduat",
            ad="TL vadeli mevduat",
            net_proxy=tl_net,
            beklenen_getiri_pct=tl_net,
            maliyet_pct=0.0,
            maliyet_kalemleri={},
            etiket="TL",
        )
    ]
    for f in fon_adaylari or []:
        adaylar.append(_fon_aday(f, kisa_vade=kisa_vade, iktisap_donemi=donem))

    kazanan, yedek, gerekce = _kazanan_sec(
        adaylar, min_fark=min_fark, tercih_tur="mevduat" if kisa_vade else None,
    )
    dilim_pay = max_pay if kazanan.tur == "tefas" else 0.0
    return DilimKarari(
        dilim="tl_deposit",
        kazanan=kazanan,
        yedek=yedek,
        gerekce=gerekce,
        dilim_pay=dilim_pay,
        notlar=[
            "Stopaj/TGO yalnızca net_proxy karşılaştırmasında; skor getirisi brüt.",
        ],
    )


def dilim_karari_fx(
    *,
    pb: str,
    fx_w: float,
    mevduat_ozet: Any = None,
    fon_adaylari: Optional[Sequence[Any]] = None,
    etf_adaylari: Optional[Sequence[Tuple[str, str, str]]] = None,
    kisa_vade: bool = False,
    iktisap_donemi: Optional[str] = None,
) -> Optional[DilimKarari]:
    """pb: EUR | USD — döviz mevduat vs serbest döviz fon vs (uzun) hisse ETF."""
    if fx_w < 0.005:
        return None
    donem = iktisap_donemi or getattr(
        config, "TEFAS_STOPAJ_VARSAYILAN_DONEM", VARSAYILAN_DONEM
    )
    min_fark = float(getattr(config, "ARAC_MIN_FARK_PCT", 0.5))
    max_pay = float(getattr(config, "ETF_DILIM_PAY", 0.45))
    fx_makas = float(getattr(config, "FX_CEVIRIM_MAKAS_PCT", 0.3))
    ter = float(getattr(config, "ETF_TER_VARSAYILAN", 0.07))

    if pb.upper() == "EUR":
        mev_net = float(getattr(mevduat_ozet, "eur_mevduat_net", 0) or 0) if mevduat_ozet else 0.0
        dilim = "eur_cash"
        mev_ad = "EUR vadeli mevduat"
    else:
        mev_net = _usd_mevduat_net(mevduat_ozet)
        dilim = "usd_cash"
        mev_ad = "USD vadeli mevduat"

    adaylar: List[AracAday] = [
        AracAday(
            tur="mevduat",
            ad=mev_ad,
            net_proxy=mev_net,
            beklenen_getiri_pct=mev_net,
            etiket=pb.upper(),
        )
    ]
    for f in fon_adaylari or []:
        adaylar.append(_fon_aday(f, kisa_vade=kisa_vade, iktisap_donemi=donem))

    if not kisa_vade and etf_adaylari:
        # Hisse ETF: brüt proxy yoksa mevduat + risk primi yerine düşük net
        # (sinyal yokken seçilmesin diye mevduat+min_fark altına koy)
        for ticker, ad, _sektor in etf_adaylari[:2]:
            beklenen = mev_net + 3.0  # muhafazakâr büyüme primi varsayımı
            maliyet, kalemler = maliyet_suruklenmesi_yillik(
                ter_pct=ter,
                makas_pct=fx_makas,
                beklenen_getiri_pct=beklenen,
            )
            adaylar.append(
                AracAday(
                    tur="etf",
                    ad=f"{ticker} · {ad}",
                    kod=ticker,
                    net_proxy=beklenen - maliyet,
                    beklenen_getiri_pct=beklenen,
                    maliyet_pct=maliyet,
                    maliyet_kalemleri=kalemler,
                    etiket="ETF",
                )
            )

    kazanan, yedek, gerekce = _kazanan_sec(
        adaylar, min_fark=min_fark, tercih_tur="mevduat" if kisa_vade else None,
    )
    if kazanan.tur == "etf":
        dilim_pay = max_pay
    elif kazanan.tur == "tefas":
        dilim_pay = min(max_pay, 0.50)
    else:
        dilim_pay = 0.0
    return DilimKarari(
        dilim=dilim,
        kazanan=kazanan,
        yedek=yedek,
        gerekce=gerekce,
        dilim_pay=dilim_pay,
    )


def dilim_karari_altin(
    *,
    gold_w: float,
    altin_3a_momentum: Optional[float] = None,
    fon_adaylari: Optional[Sequence[Any]] = None,
    kisa_vade: bool = False,
    iktisap_donemi: Optional[str] = None,
) -> Optional[DilimKarari]:
    if gold_w < 0.005:
        return None
    donem = iktisap_donemi or getattr(
        config, "TEFAS_STOPAJ_VARSAYILAN_DONEM", VARSAYILAN_DONEM
    )
    min_fark = float(getattr(config, "ARAC_MIN_FARK_PCT", 0.5))
    makas = float(getattr(config, "ALTIN_FIZIKI_MAKAS_PCT", 2.0))
    sgld_ter = float(getattr(config, "ETF_SGLD_TER", 0.12))

    mom = float(altin_3a_momentum) if altin_3a_momentum is not None else 0.0
    # 3A → kaba yıllık proxy
    beklenen_fizik = mom * 4.0 if abs(mom) > 0.01 else 4.0
    maliyet_f, kalem_f = maliyet_suruklenmesi_yillik(
        makas_pct=makas / 2.0,
        beklenen_getiri_pct=beklenen_fizik,
    )
    if kisa_vade:
        maliyet_f += 1.0  # kısa vadede fiziki makas cezası
        kalem_f["kisa_vade_ceza"] = 1.0

    adaylar: List[AracAday] = [
        AracAday(
            tur="fiziki",
            ad="Fiziki / gram altın",
            net_proxy=beklenen_fizik - maliyet_f,
            beklenen_getiri_pct=beklenen_fizik,
            maliyet_pct=maliyet_f,
            maliyet_kalemleri=kalem_f,
            etiket="ALTIN",
        )
    ]
    for f in fon_adaylari or []:
        adaylar.append(_fon_aday(f, kisa_vade=kisa_vade, iktisap_donemi=donem))

    beklenen_etf = beklenen_fizik
    maliyet_e, kalem_e = maliyet_suruklenmesi_yillik(
        ter_pct=sgld_ter,
        makas_pct=float(getattr(config, "FX_CEVIRIM_MAKAS_PCT", 0.3)),
        beklenen_getiri_pct=beklenen_etf,
    )
    adaylar.append(
        AracAday(
            tur="etf",
            ad="SGLD (altın ETF)",
            kod="SGLD",
            net_proxy=beklenen_etf - maliyet_e,
            beklenen_getiri_pct=beklenen_etf,
            maliyet_pct=maliyet_e,
            maliyet_kalemleri=kalem_e,
            etiket="ETF",
        )
    )

    kazanan, yedek, gerekce = _kazanan_sec(
        adaylar, min_fark=min_fark, tercih_tur="fiziki" if kisa_vade else None,
    )
    # Altında dilim_pay: fon/ETF kazanırsa sınıfın tamamı o araca yönlenir (gösterim)
    dilim_pay = 1.0 if kazanan.tur in ("tefas", "etf") else 0.0
    return DilimKarari(
        dilim="gold",
        kazanan=kazanan,
        yedek=yedek,
        gerekce=gerekce,
        dilim_pay=dilim_pay,
    )


def dinamik_arac_kararlari(
    *,
    agirliklar: Dict[str, float],
    mevduat_ozet: Any = None,
    tefas_fonlar: Optional[Sequence[Any]] = None,
    etf_list: Optional[Sequence[Tuple[str, str, str]]] = None,
    kisa_vade: bool = False,
    altin_3a_momentum: Optional[float] = None,
    iktisap_donemi: Optional[str] = None,
) -> List[DilimKarari]:
    """Tüm makro dilimler için araç kararları (mevcut ağırlıklar > eşik)."""
    fonlar = list(tefas_fonlar or [])
    tl_fon = [
        f for f in fonlar
        if getattr(f, "kategori", "") in ("para_piyasasi", "borclanma", "katilim", "degisken", "fon_sepeti", "hisse")
        or getattr(f, "para_birimi", "TL") == "TL"
    ]
    fx_fon = [
        f for f in fonlar
        if getattr(f, "kategori", "") == "serbest_doviz"
        or "DOVIZ" in (getattr(f, "ad", "") or "").upper()
        or "AVRO" in (getattr(f, "ad", "") or "").upper()
    ]
    altin_fon = [
        f for f in fonlar
        if getattr(f, "kategori", "") == "altin_emtia"
        or "ALTIN" in (getattr(f, "ad", "") or "").upper()
    ]

    out: List[DilimKarari] = []
    k_tl = dilim_karari_tl(
        tl_w=float(agirliklar.get("tl_deposit", 0) or 0),
        mevduat_ozet=mevduat_ozet,
        fon_adaylari=tl_fon[:5],
        kisa_vade=kisa_vade,
        iktisap_donemi=iktisap_donemi,
    )
    if k_tl:
        out.append(k_tl)

    # FX: EUR dilimi öncelikli (daha büyük genelde); USD ayrı
    k_eur = dilim_karari_fx(
        pb="EUR",
        fx_w=float(agirliklar.get("eur_cash", 0) or 0),
        mevduat_ozet=mevduat_ozet,
        fon_adaylari=fx_fon[:3],
        etf_adaylari=etf_list,
        kisa_vade=kisa_vade,
        iktisap_donemi=iktisap_donemi,
    )
    if k_eur:
        out.append(k_eur)

    k_usd = dilim_karari_fx(
        pb="USD",
        fx_w=float(agirliklar.get("usd_cash", 0) or 0),
        mevduat_ozet=mevduat_ozet,
        fon_adaylari=[],
        etf_adaylari=None,  # ETF payı EUR diliminden yönetilir
        kisa_vade=kisa_vade,
        iktisap_donemi=iktisap_donemi,
    )
    if k_usd:
        out.append(k_usd)

    k_g = dilim_karari_altin(
        gold_w=float(agirliklar.get("gold", 0) or 0),
        altin_3a_momentum=altin_3a_momentum,
        fon_adaylari=altin_fon[:3],
        kisa_vade=kisa_vade,
        iktisap_donemi=iktisap_donemi,
    )
    if k_g:
        out.append(k_g)
    return out
