# -*- coding: utf-8 -*-
"""
Türkiye Mevduat Faiz Oranları
==============================
Öncelik: Yapı Kredi (otomatik) → EVDS → acil yedek.
"""
from dataclasses import dataclass, field
import os
from typing import List, Optional

import config
import data_sources as ds
from yapikredi_rates import YapikrediMevduat, net_brut_oran, stopaj_orani, yapikredi_tl_faizleri


@dataclass
class MevduatOrani:
    vade: str
    brut_yillik: float
    net_yillik: float
    reel_yillik: Optional[float]
    kaynak: str
    vade_gun: Optional[int] = None


@dataclass
class MevduatKarsilastirma:
    oranlar: List[MevduatOrani] = field(default_factory=list)
    enflasyon: float = 35.0
    en_iyi_vade: str = ""
    en_iyi_net: float = 0.0
    en_iyi_reel: float = 0.0
    eur_mevduat_net: float = 0.0
    tl_mevduat_kazanir: bool = False
    ozet: str = ""
    uyarilar: List[str] = field(default_factory=list)
    veri_kaynagi: str = ""
    profil_vade: str = ""
    profil_vade_net: float = 0.0
    profil_vade_reel: float = 0.0
    # Yerel reel ≠ EUR bazlı getiri — raporda ayrı gösterilir
    profil_vade_eur_tahmini: float = 0.0
    breakeven_eur_try: Optional[float] = None
    kur_spot_eur_try: Optional[float] = None
    getiri_notu: str = ""


@dataclass
class TlVadeSonuOzeti:
    """Vade sonu net tutar simülasyonu — taban açıkça portföy dilimi veya manuel tutar."""
    taban: str  # portfoy_dilimi | manuel
    toplam_eur: float
    tl_agirlik: float
    tl_dilim_eur: float
    kur: float
    anapara_tl: float
    gun: int
    brut_oran: float
    stopaj_orani: float
    brut_faiz: float
    stopaj_tutar: float
    net_tl: float
    net_eur: float


def tl_vade_sonu_hesapla(
    toplam_eur: float,
    tl_agirlik: float,
    eur_try: float,
    brut_yillik: float,
    gun: int,
    manuel_anapara_tl: Optional[float] = None,
) -> Optional[TlVadeSonuOzeti]:
    """
    Vade sonu net tutar simülasyonu.
    manuel_anapara_tl verilirse portföy dilimi yerine o tutar kullanılır.
    """
    if not eur_try or eur_try <= 0 or gun <= 0:
        return None

    if manuel_anapara_tl is not None and manuel_anapara_tl > 0:
        taban = "manuel"
        anapara_tl = float(manuel_anapara_tl)
        tl_dilim_eur = anapara_tl / eur_try
        tl_agirlik_eff = tl_dilim_eur / toplam_eur if toplam_eur > 0 else 0.0
    else:
        taban = "portfoy_dilimi"
        tl_dilim_eur = toplam_eur * tl_agirlik
        anapara_tl = tl_dilim_eur * eur_try
        tl_agirlik_eff = tl_agirlik

    if anapara_tl <= 0:
        return None

    stopaj = stopaj_orani(gun, "TL")
    brut_faiz = anapara_tl * brut_yillik * (gun / 365)
    stopaj_tutar = brut_faiz * stopaj
    net_tl = anapara_tl + brut_faiz - stopaj_tutar

    return TlVadeSonuOzeti(
        taban=taban,
        toplam_eur=toplam_eur,
        tl_agirlik=tl_agirlik_eff,
        tl_dilim_eur=tl_dilim_eur,
        kur=eur_try,
        anapara_tl=anapara_tl,
        gun=gun,
        brut_oran=brut_yillik,
        stopaj_orani=stopaj,
        brut_faiz=brut_faiz,
        stopaj_tutar=stopaj_tutar,
        net_tl=net_tl,
        net_eur=net_tl / eur_try,
    )


def tmsf_uyari_satirlari(anapara_tl: float) -> List[str]:
    """TMSF sigorta limiti — aşım uyarısı veya bilgi notu."""
    limit = config.TMSF_SIGORTA_LIMITI_TL
    if anapara_tl <= 0:
        return []
    if anapara_tl > limit:
        return [
            f"TMSF sigorta limiti ({limit:,.0f} TL) aşılıyor — "
            f"mevduat tutarı ~{anapara_tl:,.0f} TL. "
            f"Tutarı birden fazla bankaya bölmek sigorta kapsamını genişletir."
        ]
    return [
        f"TMSF bilgi: mevduat tutarı ~{anapara_tl:,.0f} TL — "
        f"bireysel sigorta limiti {limit:,.0f} TL altında."
    ]


def tl_vade_sonu_rapor_metni(ozet: TlVadeSonuOzeti) -> str:
    """PDF/HTML için şeffaf vade sonu net tutar açıklaması."""
    if ozet.taban == "manuel":
        taban = (
            f"Taban: **sizin girdiğiniz mevduat tutarı** "
            f"(~{ozet.anapara_tl:,.0f} TL ≈ {ozet.tl_dilim_eur:,.0f} EUR @ {ozet.kur:.2f})."
        )
    else:
        portfoy_tl = ozet.toplam_eur * ozet.kur
        taban = (
            f"Taban: **önerilen TL mevduat dilimi** — portföyün tamamı değil "
            f"({ozet.toplam_eur:,.0f} EUR × %{ozet.tl_agirlik * 100:.1f} = "
            f"{ozet.tl_dilim_eur:,.0f} EUR → ~{ozet.anapara_tl:,.0f} TL @ {ozet.kur:.2f}; "
            f"tüm portföy ~{portfoy_tl:,.0f} TL)."
        )
    return (
        f"Vade sonu net tutar simülasyonu — {taban} "
        f"Stopaj %{ozet.stopaj_orani * 100:.0f} ({config.TL_STOPAJ_KAYNAK}): "
        f"brüt faiz +{ozet.brut_faiz:,.0f} TL, stopaj −{ozet.stopaj_tutar:,.0f} TL → "
        f"vade sonu ~{ozet.net_tl:,.0f} TL (~{ozet.net_eur:,.0f} EUR)."
    )


def _eur_bazli_tahmini(net_yillik_pct: float, tl_enflasyon: float) -> float:
    """Reel kur sabit varsayımı: TL'nin EUR karşısında enflasyon farkı kadar zayıfladığı senaryo."""
    return net_yillik_pct - (tl_enflasyon - config.EUR_ENFLASYON_VARSAYILAN)


from breakeven import breakeven_eur_try, profil_mevduat_parametreleri


def _getiri_notu_metni(
    reel_yerel: float,
    eur_tahmini: float,
    eur_try: Optional[float],
    breakeven: Optional[float],
) -> str:
    satirlar = [
        f"Yerel reel (TL enflasyonu): {reel_yerel:+.1f} pp — TL satın alma gücünü ölçer; "
        f"EUR kazancı garantisi değildir.",
        f"EUR bazlı tahmini (reel kur sabit varsayımı): {eur_tahmini:+.1f} pp — "
        f"kur enflasyondan hızlı giderse EUR bazında zarar mümkün.",
    ]
    if eur_try and breakeven:
        oran = eur_try / breakeven
        satirlar.append(
            f"Başa baş kur: spot {eur_try:.2f} · eşit getiri kuru ≈ {breakeven:.2f} "
            f"(oran {oran:.2f}) — 1.0 üzeri TL mevduat EUR mevduata göre avantajlı sayılır."
        )
    return " ".join(satirlar)


def _evds_mevduat_faizi(api_key: str) -> Optional[float]:
    """TCMB ağırlıklı ortalama TL mevduat faizi."""
    items = ds._evds_get("TP.KTF13", api_key, gun_sayisi=90)
    if not items:
        return None
    try:
        for item in reversed(items):
            for k, v in item.items():
                if k in ("Tarih", "UNIXTIME"):
                    continue
                if v not in (None, "", "None"):
                    val = float(str(v).replace(",", "."))
                    return val / 100 if val > 1 else val
    except Exception:
        pass
    return None


def _oran_hesapla(
    vade: str,
    brut: float,
    enflasyon: float,
    kaynak: str,
    vade_gun: Optional[int] = None,
    doviz: str = "TL",
) -> MevduatOrani:
    brut_dec = brut if brut <= 1 else brut / 100
    gun = vade_gun or 365
    net_dec = net_brut_oran(brut_dec * 100, gun, doviz)
    reel = net_dec * 100 - enflasyon
    return MevduatOrani(
        vade=vade,
        brut_yillik=brut_dec,
        net_yillik=net_dec,
        reel_yillik=reel,
        kaynak=kaynak,
        vade_gun=gun,
    )


def _ykb_oranlari_ekle(
    oranlar: List[MevduatOrani],
    ykb: YapikrediMevduat,
    enflasyon: float,
) -> None:
    kaynak = ykb.kaynak
    oranlar.extend([
        _oran_hesapla("TL 3 ay", ykb.tl_3ay_brut, enflasyon, kaynak, 92),
        _oran_hesapla("TL 6 ay", ykb.tl_6ay_brut, enflasyon, kaynak, 181),
        _oran_hesapla("TL 1 yıl", ykb.tl_1y_brut, enflasyon, kaynak, 365),
    ])


def mevduat_analizi(
    enflasyon: Optional[float] = None,
    profil_vade: Optional[str] = None,
    eur_try: Optional[float] = None,
    kalan_gun: Optional[int] = None,
) -> MevduatKarsilastirma:
    uyarilar: List[str] = []
    enflasyon = enflasyon or float(os.getenv("ENFLASYON_TR_VARSAYILAN", "35"))
    oranlar: List[MevduatOrani] = []
    veri_kaynagi = ""

    ykb = yapikredi_tl_faizleri()
    if ykb:
        _ykb_oranlari_ekle(oranlar, ykb, enflasyon)
        veri_kaynagi = f"{ykb.kaynak} · {ykb.cekim_zamani}"
    else:
        uyarilar.append("Yapı Kredi faizleri şu an çekilemedi — yedek kaynak deneniyor.")
        evds_brut = _evds_mevduat_faizi(config.EVDS_API_KEY)
        if evds_brut is not None:
            oranlar.append(_oran_hesapla("TL 1 yıl (EVDS)", evds_brut, enflasyon, "TCMB EVDS", 365))
            veri_kaynagi = "TCMB EVDS (canlı)"
        else:
            oranlar.append(
                _oran_hesapla(
                    "TL 1 yıl (yedek)",
                    config.TL_MEVDUAT_BRUT_FAIZ_VARSAYILAN,
                    enflasyon,
                    "Acil yedek",
                    365,
                )
            )
            veri_kaynagi = "Acil yedek — Yapı Kredi/EVDS erişilemedi"
            uyarilar.append("TL mevduat faizi otomatik alınamadı — geçici yedek kullanıldı.")

    eur_brut = float(config.EUR_MEVDUAT_YILLIK_FAIZ)
    eur_net = net_brut_oran(eur_brut * 100, 365, "EUR")
    oranlar.append(
        MevduatOrani(
            "EUR mevduat",
            eur_brut if eur_brut <= 1 else eur_brut / 100,
            eur_net,
            eur_net * 100 - 2.0,
            "Yapı Kredi / piyasa ort. (EUR döviz stopaj %25)",
            365,
        )
    )

    usd_brut = 0.04
    usd_net = net_brut_oran(usd_brut * 100, 365, "USD")
    oranlar.append(
        MevduatOrani(
            "USD mevduat",
            usd_brut if usd_brut <= 1 else usd_brut / 100,
            usd_net,
            usd_net * 100 - 2.5,
            "Yapı Kredi / piyasa ort. (USD döviz stopaj %25)",
            365,
        )
    )

    tl_oranlar = [o for o in oranlar if o.vade.startswith("TL")]
    en_iyi = max(tl_oranlar, key=lambda x: x.reel_yillik or -999)

    profil_oran = None
    if profil_vade:
        profil_oran = next((o for o in tl_oranlar if o.vade == profil_vade), None)
        if profil_oran is None:
            # "TL 3 ay" vs "TL 3 ay (EVDS)" gibi esnek eşleşme
            profil_oran = next(
                (o for o in tl_oranlar if profil_vade.replace(" (EVDS)", "") in o.vade),
                None,
            )
    profil_kaynak = profil_oran or en_iyi
    profil_gun_param = kalan_gun or profil_kaynak.vade_gun or 365
    net_tl_dec, gun_unified, faiz_kaynak = profil_mevduat_parametreleri(
        profil_gun_param,
        None,
    )
    net_pct = net_tl_dec * 100
    reel_yerel = net_pct - enflasyon
    eur_tahmini = _eur_bazli_tahmini(net_pct, enflasyon)
    breakeven = None
    if eur_try:
        breakeven = breakeven_eur_try(eur_try, net_tl_dec, gun_unified)
    getiri_notu = _getiri_notu_metni(reel_yerel, eur_tahmini, eur_try, breakeven)
    if faiz_kaynak:
        getiri_notu += f" Hesap: {gun_unified} gün, {faiz_kaynak}."

    tl_kazanir = reel_yerel > 0 and eur_tahmini > (eur_net * 100 - config.EUR_ENFLASYON_VARSAYILAN)

    if tl_kazanir:
        hedef = profil_kaynak.vade if profil_oran else en_iyi.vade
        ozet = (
            f"Profil vadenize uygun **{hedef}**: yerel reel ~%{reel_yerel:.1f} (TL enflasyonu), "
            f"EUR bazlı tahmini ~%{eur_tahmini:.1f} — kur riski devam eder; 4 kapı kuralları geçerli."
            if profil_oran
            else (
                f"TL mevduat ({en_iyi.vade}) yerel reel ~%{reel_yerel:.1f}; "
                f"EUR bazlı tahmini ~%{eur_tahmini:.1f} — kur riski ve 4 kapı geçerli."
            )
        )
    else:
        hedef = profil_kaynak.vade if profil_oran else en_iyi.vade
        ozet = (
            f"Profil vadeniz (**{hedef}**): yerel reel ~%{reel_yerel:.1f}, "
            f"EUR bazlı tahmini ~%{eur_tahmini:.1f} — enflasyon/kur riski sınırda; "
            f"EUR/altın ağırlığı makro tahsisle uyumlu."
            if profil_oran
            else (
                f"TL mevduat yerel reel ~%{reel_yerel:.1f}, EUR bazlı tahmini ~%{eur_tahmini:.1f} — "
                f"EUR/altın ağırlığı makro tahsisle uyumlu."
            )
        )

    return MevduatKarsilastirma(
        oranlar=oranlar,
        enflasyon=enflasyon,
        en_iyi_vade=en_iyi.vade,
        en_iyi_net=(en_iyi.net_yillik or 0) * 100,
        en_iyi_reel=en_iyi.reel_yillik or 0,
        eur_mevduat_net=eur_net * 100,
        tl_mevduat_kazanir=tl_kazanir,
        ozet=ozet,
        uyarilar=uyarilar,
        veri_kaynagi=veri_kaynagi,
        profil_vade=profil_kaynak.vade,
        profil_vade_net=net_pct,
        profil_vade_reel=reel_yerel,
        profil_vade_eur_tahmini=eur_tahmini,
        breakeven_eur_try=breakeven,
        kur_spot_eur_try=eur_try,
        getiri_notu=getiri_notu,
    )
