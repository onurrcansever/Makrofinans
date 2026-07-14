# -*- coding: utf-8 -*-
"""
Makro Rejim Tespiti
====================
Kurumsal sistemlerdeki "regime switching" mantığının şeffaf, kural tabanlı
versiyonu. Her rejim, varlık skorlarına farklı ağırlık uygular.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import config
from macro_data import MacroSnapshot
from siyasi_esik import esikler


@dataclass
class RejimSonucu:
    rejim: str
    etiket: str
    aciklama: str
    guven: float  # 0-1
    adimlar: List[str] = field(default_factory=list)
    degisim_gerekce: str = ""
    donduruldu: bool = False
    komşu_rejimler: tuple = ()
    gecis_notu: str = ""


REJIMLER = {
    "KRIZ": "Kriz / jeopolitik şok",
    "EM_STRES": "Gelişen piyasa stresi",
    "TL_FIRSAT": "TL mevduat fırsatı",
    "ENFLASYON_KORUMA": "Enflasyon koruma",
    "RISK_ON": "Risk iştahı yüksek",
    "NOTR": "Nötr / dengeli",
    "BELIRSIZ": "Belirsiz / geçiş bölgesi",
}


def rejim_tespit(snap: MacroSnapshot) -> RejimSonucu:
    v = snap.veri
    adimlar: List[str] = []

    # --- Kriz kontrolü (en yüksek öncelik) ---
    siyasi = v.siyasi_risk_makale_sayisi
    es = esikler()
    if siyasi is not None and siyasi >= es["kriz"]:
        adimlar.append(
            f"Siyasi haber ({siyasi}) >= kriz eşiği ({es['kriz']}, taban {es['taban']}) -> KRİZ"
        )
        return RejimSonucu(
            rejim="KRIZ",
            etiket=REJIMLER["KRIZ"],
            aciklama="Pozisyon açmayın; likit ve güvenli varlıklara yönelin.",
            guven=0.9,
            adimlar=adimlar,
        )

    cds = v.cds_5y_bp
    if cds is not None and cds > 400:
        adimlar.append(f"CDS ({cds:.0f}bp) > 400 -> KRİZ benzeri stres")
        return RejimSonucu(
            rejim="KRIZ",
            etiket=REJIMLER["KRIZ"],
            aciklama="Ülke risk primi kritik seviyede; TL ve gümüşten kaçının.",
            guven=0.85,
            adimlar=adimlar,
        )

    # --- EM stres ---
    em_stres_puan = 0
    if cds is not None and cds > 280:
        em_stres_puan += 1
        adimlar.append(f"CDS yüksek ({cds:.0f}bp)")
    if v.rezerv_artiyor is False:
        em_stres_puan += 1
        adimlar.append("TCMB rezervleri azalıyor")
    if snap.vix is not None and snap.vix > 25:
        em_stres_puan += 1
        adimlar.append(f"VIX yükselmiş ({snap.vix:.1f})")
    if snap.bist_vol_30g is not None and snap.bist_vol_30g > 42:
        em_stres_puan += 1
        adimlar.append(f"BIST vol yüksek ({snap.bist_vol_30g:.1f}% — yerel stres)")

    if em_stres_puan >= 2:
        return RejimSonucu(
            rejim="EM_STRES",
            etiket=REJIMLER["EM_STRES"],
            aciklama="Gelişen piyasa stresi; EUR/USD ve altın ağırlığı artırılmalı.",
            guven=0.7 + 0.1 * min(em_stres_puan, 2),
            adimlar=adimlar,
        )

    # --- TL fırsat ---
    enflasyon = snap.enflasyon_tr_yillik or 35.0
    tcmb = v.tcmb_politika_faizi or (v.tl_mevduat_brut_faiz or 0.40) * 100
    reel_faiz = tcmb - enflasyon
    savas_yuksek = (v.savas_risk_makale_sayisi or 0) >= config.SAVAS_RISK_YUKSEK_ESIGI
    savas_aktif = (v.savas_risk_makale_sayisi or 0) >= config.SAVAS_RISK_ESIGI
    jeopolitik_kesinti = savas_aktif  # Kapı 1b ×0.9 jeopolitik çarpanı aktifken risk-on yasak
    # Ham sayılardan anlık config eşikleriyle yeniden hesapla.
    # Önbellekteki tl_makro_risk_aktif eski eşiklerle hesaplanmış olabilir;
    # ham sayılar (tl_faiz_indirim_haber, tl_erken_secim_haber) varsa onlara güven.
    if v.tl_faiz_indirim_haber is not None or v.tl_erken_secim_haber is not None:
        from tl_makro_risk import _anormal, _secim_anormal
        faiz_yuksek = (v.tl_faiz_indirim_haber or 0) >= config.TL_MAKRO_FAIZ_ESIGI or (
            v.tl_faiz_indirim_haber is not None
            and _anormal(
                v.tl_faiz_indirim_haber,
                "faiz_indirim",
                config.TL_MAKRO_FAIZ_TABAN_VARSAYILAN,
                config.TL_MAKRO_ANORMAL_CARPAN,
            )
        )
        secim_yuksek = _secim_anormal(
            v.tl_erken_secim_haber or 0,
            "erken_secim",
            config.TL_MAKRO_SECIM_TABAN_VARSAYILAN,
            config.TL_MAKRO_ANORMAL_CARPAN,
        )
        tl_makro_risk = faiz_yuksek or secim_yuksek
    else:
        tl_makro_risk = bool(v.tl_makro_risk_aktif)
    cds_uyari = list(getattr(snap, "cekim_uyarilari", []) or [])
    cds_supheli = any("CDS" in u for u in cds_uyari)
    tl_firsat = (
        cds is not None
        and cds < 280
        and reel_faiz > 0
        and (siyasi or 0) < es["temkin"]
        and not tl_makro_risk
    )
    if tl_firsat:
        adimlar.append(f"Reel faiz pozitif (~{reel_faiz:.1f}pp), CDS makul -> TL fırsat")
        # Güven, reel faiz marjı ve CDS mesafesine göre ölçeklenir (sabit 0.75 yerine)
        guven = 0.60 + min(0.20, reel_faiz * 0.04) + min(0.10, (280 - cds) / 400)
        return RejimSonucu(
            rejim="TL_FIRSAT",
            etiket=REJIMLER["TL_FIRSAT"],
            aciklama="TL mevduat cazip; mevcut 4 kapılı tavan kuralları geçerli.",
            guven=round(min(guven, 0.9), 2),
            adimlar=adimlar,
        )
    if not tl_firsat and tl_makro_risk and cds is not None and cds < 280 and reel_faiz > 0:
        parcalar = []
        if v.tl_faiz_indirim_haber and v.tl_faiz_indirim_haber >= config.TL_MAKRO_FAIZ_ESIGI:
            parcalar.append(f"faiz indirimi beklentisi ({v.tl_faiz_indirim_haber} haber)")
        if v.tl_erken_secim_anormal:
            parcalar.append(f"erken seçim anormal sıklık ({v.tl_erken_secim_haber} haber)")
        neden = "; ".join(parcalar) if parcalar else "TL makro haber riski"
        adimlar.append(
            f"Reel faiz pozitif ama {neden} -> TL fırsat rejimi askıya alındı"
        )

    # --- Enflasyon koruma ---
    if enflasyon > 30 and (cds or 0) > 220:
        adimlar.append(f"Enflasyon yüksek ({enflasyon:.1f}%), CDS orta -> altın ağırlığı")
        return RejimSonucu(
            rejim="ENFLASYON_KORUMA",
            etiket=REJIMLER["ENFLASYON_KORUMA"],
            aciklama="Satın alma gücü koruma modu; altın ve EUR ağırlığı artırılır.",
            guven=0.7,
            adimlar=adimlar,
        )

    # --- Risk-on — jeopolitik/CDS şüpheliyken kapalı ---
    if (
        snap.vix is not None
        and snap.vix < 16
        and (cds or 999) < 250
        and not savas_aktif
        and not jeopolitik_kesinti
        and not cds_supheli
    ):
        adimlar.append(f"VIX düşük ({snap.vix:.1f}), CDS sakin -> risk iştahı")
        return RejimSonucu(
            rejim="RISK_ON",
            etiket=REJIMLER["RISK_ON"],
            aciklama="Piyasa sakin; gümüş ve kontrollü TL tahsisi değerlendirilebilir.",
            guven=0.65,
            adimlar=adimlar,
        )
    if snap.vix is not None and snap.vix < 16 and (cds or 999) < 250:
        if savas_aktif or jeopolitik_kesinti:
            adimlar.append(
                f"Jeopolitik haber ({v.savas_risk_makale_sayisi}) yüksek -> risk-on iptal, nötr"
            )
        elif cds_supheli:
            adimlar.append("CDS çapraz kontrol / sıçrama uyarısı -> risk-on iptal, nötr")

    adimlar.append("Belirgin sinyal yok -> nötr rejim")
    return RejimSonucu(
        rejim="NOTR",
        etiket=REJIMLER["NOTR"],
        aciklama="Dengeli dağılım; mevcut makro verilere göre kademeli tahsis.",
        guven=0.6,
        adimlar=adimlar,
    )
