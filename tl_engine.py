# -*- coding: utf-8 -*-
"""
TL mevduat karar motoru v2 — duygu, histerezis, explain katmanı.
Mevcut karar_ver() imzasını bozmaz; ana akış buradan beslenir.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Optional

import config
from decision_engine import KararSonucu, PiyasaVerisi, karar_ver
from gate_hysteresis import KRITIK_VETO_TAVAN, cds_tavan_histerezis, haber_kriz_histerezis, son_tavan_kaydet
from news_sentiment_scan import SentimentPaketi, sentiment_tara
from ppk_awareness import ppk_faiz_takip, ppk_fomc_durumu, ppk_teyit_atla
from siyasi_etkin import kap1_haber_sayisi, siyasi_kriz_mi
from tl_decision_explain import TlExplainSonuc, explain_tl_decision, explain_to_dict


@dataclass
class TlKararPaketi:
    sonuc: KararSonucu
    sentiment: SentimentPaketi
    explain: TlExplainSonuc
    explain_dict: List[dict] = field(default_factory=list)
    etkin_siyasi: int = 0
    etkin_jeopolitik: int = 0
    kritik_veto: bool = False
    ppk_bekle: bool = False
    ppk_notu: str = ""


def _veri_duzenle(veri: PiyasaVerisi, sentiment: SentimentPaketi) -> PiyasaVerisi:
    """Duygu-adjusted haber sayıları — spekülasyon şişirmesi kapı sayımına yansımaz."""
    v = deepcopy(veri)
    raw_s = sentiment.siyasi.haber_sayisi or 0
    etkin_s = sentiment.etkin_siyasi
    kap1_s = sentiment.kap1_siyasi or kap1_haber_sayisi(raw_s, etkin_s)
    if raw_s > 0 or veri.siyasi_risk_makale_sayisi:
        v.siyasi_risk_makale_sayisi = kap1_s
    if sentiment.jeopolitik.haber_sayisi > 0 or veri.savas_risk_makale_sayisi:
        v.savas_risk_makale_sayisi = sentiment.etkin_jeopolitik
    return v


def tl_karar_hesapla(
    veri: PiyasaVerisi,
    vade_gun: Optional[int] = None,
    sentiment: Optional[SentimentPaketi] = None,
    canli_sentiment: bool = True,
    reel_pp: Optional[float] = None,
    profil_tavan: Optional[float] = None,
    allocation_pay: Optional[float] = None,
    onceki_tcmb_faiz: Optional[float] = None,
) -> TlKararPaketi:
    """4 Kapı v2 — duygu + histerezis + explain."""
    if onceki_tcmb_faiz is not None and veri.tcmb_politika_faizi is not None:
        ppk_faiz_takip(onceki_tcmb_faiz, veri.tcmb_politika_faizi)

    paket = sentiment or sentiment_tara(canli=canli_sentiment)
    ppk = ppk_fomc_durumu()

    v2 = _veri_duzenle(veri, paket)
    ham = karar_ver(v2, vade_gun=vade_gun)

    adimlar = list(ham.adimlar)
    uyarilar = list(ham.uyarilar)
    tavan = ham.tavan_oran

    # Kriz histerezisi — kap1 sayım (ham + etkin çift kapı)
    raw_s = paket.siyasi.haber_sayisi or 0
    kap1_s = paket.kap1_siyasi or kap1_haber_sayisi(raw_s, paket.etkin_siyasi)
    kriz_mi = siyasi_kriz_mi(raw_s, paket.etkin_siyasi)
    kriz_kilit, kriz_not = haber_kriz_histerezis(kap1_s)
    if kriz_kilit and not kriz_mi:
        kriz_kilit = False
        kriz_not = (
            f"etkin {paket.etkin_siyasi} / ham {raw_s} — "
            f"spekülasyon şişirmesi; kriz kilidi uygulanmadı"
        )
    if kriz_kilit and ham.kapi1_gecti:
        tavan = 0.0
        adimlar.append(f"Kapı 1 histerezis: {kriz_not}")
        uyarilar.append("[KRİTİK] Haber kriz kilidi aktif.")

    if not ham.kapi1_gecti:
        tavan = 0.0
    elif veri.cds_5y_bp is not None:
        ham_cds = tavan
        tavan, cds_not = cds_tavan_histerezis(veri.cds_5y_bp, tavan)
        if abs(tavan - ham_cds) > 1e-6:
            adimlar.append(f"Kapı 2 histerezis: {cds_not}")

    if paket.kritik_veto and tavan > KRITIK_VETO_TAVAN:
        onceki = tavan
        tavan = KRITIK_VETO_TAVAN
        adimlar.append(
            f"Kapı 1c [KRİTİK] Olay vetosu — tavan %{onceki*100:.0f} → %{tavan*100:.0f}"
        )
        uyarilar.append(
            "[KRİTİK] Olay vetosu aktif: "
            + "; ".join(paket.veto_basliklari[:3])
            + ("…" if len(paket.veto_basliklari) > 3 else "")
        )

    tavan = min(tavan, config.MUTLAK_TAVAN)
    son_tavan_kaydet(tavan)

    # Duygu satırları
    if paket.siyasi.haber_sayisi:
        adimlar.insert(
            1,
            f"Duygu (siyasi): {paket.siyasi.haber_sayisi} haber, "
            f"ort {paket.siyasi.ort_duygu:+.2f} → etkin {paket.etkin_siyasi}, "
            f"kapı sayımı {kap1_s}",
        )
    if paket.jeopolitik.haber_sayisi:
        adimlar.append(
            f"Duygu (jeopolitik): {paket.jeopolitik.haber_sayisi} haber, "
            f"ort {paket.jeopolitik.ort_duygu:+.2f} → etkin {paket.etkin_jeopolitik}"
        )

    if ppk.ppk_bekle and ppk.ppk_notu:
        adimlar.append(ppk.ppk_notu)
        uyarilar.append(ppk.ppk_notu)

    tahsis_eur = config.TOPLAM_EUR * tavan if ham.kapi1_gecti else 0.0

    sonuc = KararSonucu(
        kapi1_gecti=ham.kapi1_gecti and not kriz_kilit,
        kapi1_gerekce=ham.kapi1_gerekce,
        tavan_oran=tavan,
        adimlar=adimlar,
        tahsis_eur=tahsis_eur,
        tavsiye_metni=ham.tavsiye_metni,
        uyarilar=uyarilar,
    )

    explain = explain_tl_decision(
        veri,
        vade_gun=vade_gun,
        sentiment=paket,
        reel_pp=reel_pp,
        profil_tavan=profil_tavan,
        allocation_pay=allocation_pay,
    )

    return TlKararPaketi(
        sonuc=sonuc,
        sentiment=paket,
        explain=explain,
        explain_dict=explain_to_dict(explain),
        etkin_siyasi=paket.etkin_siyasi,
        etkin_jeopolitik=paket.etkin_jeopolitik,
        kritik_veto=paket.kritik_veto,
        ppk_bekle=ppk.ppk_bekle,
        ppk_notu=ppk.ppk_notu,
    )
