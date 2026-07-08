# -*- coding: utf-8 -*-
"""
TL karar denetim izi — kapı şelalesi ve bağlayıcı kısıt.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import config
from breakeven import breakeven_eur_try, profil_mevduat_parametreleri
from decision_engine import PiyasaVerisi, _cds_tavani, karar_ver
from gate_hysteresis import KRITIK_VETO_TAVAN, cds_tavan_histerezis, haber_kriz_histerezis
from news_sentiment_scan import SentimentPaketi
from siyasi_esik import esikler
from siyasi_etkin import kap1_haber_sayisi, siyasi_kriz_mi


@dataclass
class TlExplainAdim:
    adim: str
    deger: Optional[str] = None
    etki: Optional[str] = None
    kirdi_mi: bool = False
    pay_once: Optional[float] = None
    pay_sonra: Optional[float] = None


@dataclass
class TlExplainSonuc:
    adimlar: List[TlExplainAdim] = field(default_factory=list)
    ideal_pay_pct: float = 0.0
    nihai_pay_pct: float = 0.0
    baglayici_kisit: str = ""
    baglayici_etiket: str = ""
    oneri_cumlesi: str = ""


def _pct(x: float) -> str:
    return f"%{x*100:.1f}"


def explain_tl_decision(
    veri: PiyasaVerisi,
    vade_gun: Optional[int] = None,
    sentiment: Optional[SentimentPaketi] = None,
    reel_pp: Optional[float] = None,
    profil_tavan: Optional[float] = None,
    allocation_pay: Optional[float] = None,
) -> TlExplainSonuc:
    """
    Kapı şelalesi: ideal paydan nihai tavana/paya kadar her adımın etkisi.
    """
    adimlar: List[TlExplainAdim] = []
    es = esikler()

    raw_siyasi = sentiment.siyasi.haber_sayisi if sentiment else None
    etkin_siyasi = (
        sentiment.etkin_siyasi
        if sentiment
        else (veri.siyasi_risk_makale_sayisi or 0)
    )
    kap1_siyasi = (
        sentiment.kap1_siyasi
        if sentiment
        else kap1_haber_sayisi(etkin_siyasi, etkin_siyasi)
    )
    if raw_siyasi is not None:
        kap1_siyasi = sentiment.kap1_siyasi or kap1_haber_sayisi(raw_siyasi, etkin_siyasi)
    etkin_jeo = (
        sentiment.etkin_jeopolitik
        if sentiment
        else (veri.savas_risk_makale_sayisi or 0)
    )

    ideal = config.MUTLAK_TAVAN
    if reel_pp is not None and reel_pp > 0:
        ideal = min(ideal, 0.18 + min(0.12, reel_pp * 0.02))
    adimlar.append(
        TlExplainAdim(
            adim="İdeal pay (reel faiz + başabaş)",
            deger=_pct(ideal),
            pay_once=0.0,
            pay_sonra=ideal,
        )
    )

    pay = ideal
    baglayici = ("İdeal pay", "reel faiz / başabaş", ideal, ideal)

    # Kapı 1 — siyasi (kap1 sayım + çift kapı)
    kriz_mi = siyasi_kriz_mi(raw_siyasi or kap1_siyasi, etkin_siyasi)
    kriz, kriz_not = haber_kriz_histerezis(kap1_siyasi)
    if (kriz and kriz_mi) or (kap1_siyasi >= es["kriz"] and kriz_mi):
        onceki = pay
        pay = 0.0
        duygu = sentiment.siyasi.ort_duygu if sentiment else 0
        adimlar.append(
            TlExplainAdim(
                adim=(
                    f"Kapı 1 (ham {raw_siyasi or '—'}, etkin {etkin_siyasi}, "
                    f"kapı {kap1_siyasi}, duygu {duygu:+.2f})"
                ),
                etki="KRİZ — tavan %0",
                kirdi_mi=True,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        baglayici = ("Kapı 1 (siyasi)", "siyasi kriz eşiği", onceki, pay)
        return _finalize(adimlar, ideal, pay, baglayici, reel_pp)

    duygu_s = sentiment.siyasi.ort_duygu if sentiment else 0
    adimlar.append(
        TlExplainAdim(
            adim=(
                f"Kapı 1 (ham {raw_siyasi or '—'}, etkin {etkin_siyasi}, "
                f"kapı {kap1_siyasi}, duygu {duygu_s:+.2f})"
            ),
            etki="geçti",
            kirdi_mi=False,
            pay_once=pay,
            pay_sonra=pay,
        )
    )

    # Kapı 2 — CDS
    if veri.cds_5y_bp is None:
        onceki = pay
        pay = 0.0
        adimlar.append(
            TlExplainAdim(
                adim="Kapı 2 (CDS veri yok)",
                etki="tavan %0",
                kirdi_mi=True,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        baglayici = ("Kapı 2 (CDS)", "veri yok", onceki, pay)
        return _finalize(adimlar, ideal, pay, baglayici, reel_pp)

    ham_cds_tavan = _cds_tavani(veri.cds_5y_bp)
    cds_tavan, cds_not = cds_tavan_histerezis(veri.cds_5y_bp, ham_cds_tavan)
    onceki = pay
    pay = min(pay, cds_tavan)
    kirdi = pay < onceki - 1e-6
    adimlar.append(
        TlExplainAdim(
            adim=f"Kapı 2 (CDS {veri.cds_5y_bp:.0f}bp)",
            etki=f"tavan {_pct(cds_tavan)} · {cds_not}",
            kirdi_mi=kirdi,
            pay_once=onceki,
            pay_sonra=pay,
        )
    )
    if kirdi:
        baglayici = ("Kapı 2 (CDS)", f"CDS {veri.cds_5y_bp:.0f} bp", onceki, pay)

    # Kapı 3 — başabaş
    if veri.eur_try is not None:
        profil_gun = vade_gun or config.KALAN_GUN
        net_tl, gun_used, _ = profil_mevduat_parametreleri(
            profil_gun, veri.tl_mevduat_brut_faiz,
        )
        breakeven = breakeven_eur_try(veri.eur_try, net_tl, gun_used)
        oran = veri.eur_try / breakeven if breakeven else 999
        onceki = pay
        if oran >= 1.0:
            pay = pay / 2
        kirdi = pay < onceki - 1e-6
        adimlar.append(
            TlExplainAdim(
                adim=f"Kapı 3 (başabaş oran {oran:.2f})",
                etki="tavan ×0.5" if oran >= 1.0 else "geçti",
                kirdi_mi=kirdi,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        if kirdi:
            baglayici = ("Kapı 3 (başabaş)", f"spot/başabaş {oran:.2f}", onceki, pay)

    # Kapı 4 — rezerv
    onceki = pay
    if veri.rezerv_artiyor is False:
        pay = pay * config.REZERV_DUSUS_CARPANI
        etki = f"×{config.REZERV_DUSUS_CARPANI}"
    elif veri.rezerv_artiyor is None:
        pay = pay * config.REZERV_BILINMIYOR_CARPANI
        etki = f"×{config.REZERV_BILINMIYOR_CARPANI}"
    else:
        etki = "geçti"
    kirdi = pay < onceki - 1e-6
    adimlar.append(
        TlExplainAdim(
            adim="Kapı 4 (rezerv trendi)",
            etki=etki,
            kirdi_mi=kirdi,
            pay_once=onceki,
            pay_sonra=pay,
        )
    )
    if kirdi:
        baglayici = ("Kapı 4 (rezerv)", etki, onceki, pay)

    # Kapı 1b — jeopolitik (etkin)
    duygu_j = sentiment.jeopolitik.ort_duygu if sentiment else 0
    onceki = pay
    if veri.savas_risk_guvenilir is False:
        pay = pay * 0.85
        etki = "×0.85 (tarama güvensiz)"
    elif etkin_jeo >= config.SAVAS_RISK_YUKSEK_ESIGI:
        pay = pay * config.SAVAS_TAVAN_CARPANI
        etki = f"×{config.SAVAS_TAVAN_CARPANI} (etkin {etkin_jeo})"
    else:
        etki = f"etkin {etkin_jeo} — geçti"
    kirdi = pay < onceki - 1e-6
    adimlar.append(
        TlExplainAdim(
            adim=f"Kapı 1b (jeopolitik duygu {duygu_j:+.2f})",
            etki=etki,
            kirdi_mi=kirdi,
            pay_once=onceki,
            pay_sonra=pay,
        )
    )
    if kirdi:
        baglayici = ("Kapı 1b (jeopolitik)", etki, onceki, pay)

    # Kapı 1c — kritik olay vetosu
    if sentiment and sentiment.kritik_veto:
        onceki = pay
        pay = min(pay, KRITIK_VETO_TAVAN)
        adimlar.append(
            TlExplainAdim(
                adim="Kapı 1c [KRİTİK] Olay vetosu",
                etki=f"tavan {_pct(KRITIK_VETO_TAVAN)}",
                kirdi_mi=True,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        baglayici = ("Kapı 1c (kritik veto)", "≥3 kritik negatif haber", onceki, pay)

    # Kapı 1d — TL makro (mevcut)
    if veri.tl_makro_risk_aktif:
        onceki = pay
        pay = pay * config.TL_MAKRO_TAVAN_CARPANI
        adimlar.append(
            TlExplainAdim(
                adim="Kapı 1d (TL makro haber)",
                etki=f"×{config.TL_MAKRO_TAVAN_CARPANI}",
                kirdi_mi=True,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        baglayici = ("Kapı 1d (TL makro)", "faiz/erken seçim", onceki, pay)

    pay = min(pay, config.MUTLAK_TAVAN)
    if profil_tavan is not None and pay > profil_tavan:
        onceki = pay
        pay = profil_tavan
        adimlar.append(
            TlExplainAdim(
                adim="Profil / rejim tavanı",
                etki=_pct(profil_tavan),
                kirdi_mi=True,
                pay_once=onceki,
                pay_sonra=pay,
            )
        )
        baglayici = ("Profil tavanı", "risk profili", onceki, pay)

    nihai = allocation_pay if allocation_pay is not None else pay
    if allocation_pay is not None and allocation_pay < pay - 1e-6:
        adimlar.append(
            TlExplainAdim(
                adim="Tahsis motoru sınırı",
                etki=_pct(allocation_pay),
                kirdi_mi=True,
                pay_once=pay,
                pay_sonra=allocation_pay,
            )
        )
        if allocation_pay < baglayici[3]:
            baglayici = ("Tahsis skoru", "çoklu varlık dengesi", pay, allocation_pay)

    return _finalize(adimlar, ideal, nihai, baglayici, reel_pp)


def _finalize(
    adimlar: List[TlExplainAdim],
    ideal: float,
    pay: float,
    baglayici: Tuple[str, str, float, float],
    reel_pp: Optional[float],
) -> TlExplainSonuc:
    ad, etiket, _, _ = baglayici
    adimlar.append(
        TlExplainAdim(
            adim="SONUÇ",
            deger=_pct(pay),
            etki=f"bağlayıcı: {ad}",
            kirdi_mi=False,
            pay_once=ideal,
            pay_sonra=pay,
        )
    )

    if reel_pp is not None and reel_pp > 0 and pay < ideal * 0.5:
        oneri = (
            f"Faiz matematiği lehte ({reel_pp:+.1f} pp) ancak {etiket} nedeniyle "
            f"pay {_pct(pay)} ile sınırlandı. {etiket} düzelirse pay otomatik artar."
        )
    elif pay < 0.01:
        oneri = "TL payı kapılar nedeniyle sıfıra yakın — defansif varlıklar ağırlıklı kalın."
    else:
        oneri = f"TL payı {_pct(pay)} — sınırlayan: {etiket}."

    return TlExplainSonuc(
        adimlar=adimlar,
        ideal_pay_pct=ideal * 100,
        nihai_pay_pct=pay * 100,
        baglayici_kisit=ad,
        baglayici_etiket=etiket,
        oneri_cumlesi=oneri,
    )


def explain_to_dict(explain: TlExplainSonuc) -> List[Dict[str, Any]]:
    return [
        {
            "adım": a.adim,
            "değer": a.deger,
            "etki": a.etki,
            "kırptı mı": a.kirdi_mi,
            "pay önce": round(a.pay_once * 100, 1) if a.pay_once is not None else None,
            "pay sonra": round(a.pay_sonra * 100, 1) if a.pay_sonra is not None else None,
        }
        for a in explain.adimlar
    ]
