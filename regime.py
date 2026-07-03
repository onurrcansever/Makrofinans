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


@dataclass
class RejimSonucu:
    rejim: str
    etiket: str
    aciklama: str
    guven: float  # 0-1
    adimlar: List[str] = field(default_factory=list)


REJIMLER = {
    "KRIZ": "Kriz / jeopolitik şok",
    "EM_STRES": "Gelişen piyasa stresi",
    "TL_FIRSAT": "TL mevduat fırsatı",
    "ENFLASYON_KORUMA": "Enflasyon koruma",
    "RISK_ON": "Risk iştahı yüksek",
    "NOTR": "Nötr / dengeli",
}


def rejim_tespit(snap: MacroSnapshot) -> RejimSonucu:
    v = snap.veri
    adimlar: List[str] = []

    # --- Kriz kontrolü (en yüksek öncelik) ---
    siyasi = v.siyasi_risk_makale_sayisi
    if siyasi is not None and siyasi >= config.SIYASI_RISK_MAKALE_ESIGI:
        adimlar.append(f"Siyasi haber sayısı ({siyasi}) eşiği aştı -> KRİZ")
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
    tl_firsat = (
        cds is not None
        and cds < 280
        and reel_faiz > 0
        and (siyasi or 0) < config.SIYASI_RISK_MAKALE_ESIGI // 2
    )
    if tl_firsat:
        adimlar.append(f"Reel faiz pozitif (~{reel_faiz:.1f}pp), CDS makul -> TL fırsat")
        return RejimSonucu(
            rejim="TL_FIRSAT",
            etiket=REJIMLER["TL_FIRSAT"],
            aciklama="TL mevduat cazip; mevcut 4 kapılı tavan kuralları geçerli.",
            guven=0.75,
            adimlar=adimlar,
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

    # --- Risk-on ---
    if snap.vix is not None and snap.vix < 16 and (cds or 999) < 250:
        adimlar.append(f"VIX düşük ({snap.vix:.1f}), CDS sakin -> risk iştahı")
        return RejimSonucu(
            rejim="RISK_ON",
            etiket=REJIMLER["RISK_ON"],
            aciklama="Piyasa sakin; gümüş ve kontrollü TL tahsisi değerlendirilebilir.",
            guven=0.65,
            adimlar=adimlar,
        )

    adimlar.append("Belirgin sinyal yok -> nötr rejim")
    return RejimSonucu(
        rejim="NOTR",
        etiket=REJIMLER["NOTR"],
        aciklama="Dengeli dağılım; mevcut makro verilere göre kademeli tahsis.",
        guven=0.6,
        adimlar=adimlar,
    )
