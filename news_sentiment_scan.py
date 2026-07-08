# -*- coding: utf-8 -*-
"""Siyasi ve jeopolitik haber başlıkları + duygu analizi."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import config
from news_sentiment import (
    HaberDuyguSonucu,
    etkin_haber_sayisi,
    haberleri_analiz_et,
    kritik_veto_aktif,
    veto_basliklari,
)
from risk_scan import google_news_basliklari
from siyasi_etkin import kap1_haber_sayisi


@dataclass
class SentimentPaketi:
    siyasi: HaberDuyguSonucu
    jeopolitik: HaberDuyguSonucu
    etkin_siyasi: int
    etkin_jeopolitik: int
    kap1_siyasi: int
    kritik_veto: bool
    veto_basliklari: List[str]


def _sorgular(attr: str, yedek: List[str]) -> List[str]:
    return list(getattr(config, attr, yedek))


def _sorgu_max_analiz(
    sorgular: List[str],
    saat: int,
) -> Tuple[HaberDuyguSonucu, int, int, List[str]]:
    """
    Her sorguyu ayrı say — makro tarama ile uyumlu (max, birleşik toplam değil).
    Dönüş: (en yüksek kap1 sorgunun analizi, etkin, kap1, o sorgunun başlıkları)
    """
    en_iyi = haberleri_analiz_et([])
    en_iyi_etkin = 0
    en_iyi_kap1 = 0
    en_iyi_baslik: List[str] = []

    for sorgu in sorgular:
        basliklar = google_news_basliklari(sorgu, saat=saat)
        sonuc = haberleri_analiz_et(basliklar)
        etkin = etkin_haber_sayisi(sonuc.haber_sayisi, sonuc.ort_duygu)
        kap1 = kap1_haber_sayisi(sonuc.haber_sayisi, etkin)
        if kap1 > en_iyi_kap1:
            en_iyi = sonuc
            en_iyi_etkin = etkin
            en_iyi_kap1 = kap1
            en_iyi_baslik = basliklar

    return en_iyi, en_iyi_etkin, en_iyi_kap1, en_iyi_baslik


def _jeo_max_analiz(sorgular: List[str], saat: int) -> Tuple[HaberDuyguSonucu, int]:
    """Jeopolitik — sorgu başına max ham sayı (risk_scan.jeopolitik_risk_tara ile uyumlu)."""
    en_iyi = haberleri_analiz_et([])
    en_iyi_etkin = 0
    en_iyi_ham = 0

    for sorgu in sorgular:
        basliklar = google_news_basliklari(sorgu, saat=saat)
        sonuc = haberleri_analiz_et(basliklar)
        etkin = etkin_haber_sayisi(sonuc.haber_sayisi, sonuc.ort_duygu)
        if sonuc.haber_sayisi > en_iyi_ham:
            en_iyi = sonuc
            en_iyi_ham = sonuc.haber_sayisi
            en_iyi_etkin = etkin

    return en_iyi, en_iyi_etkin


def sentiment_tara(saat: Optional[int] = None, canli: bool = True) -> SentimentPaketi:
    """
    Google News başlıklarını çekip duygu analizi uygular.
    canli=False ise boş nötr paket (test / offline).
    """
    pencere = saat or config.SIYASI_RISK_TARAMA_SAAT
    if not canli:
        bos = haberleri_analiz_et([])
        return SentimentPaketi(
            siyasi=bos,
            jeopolitik=bos,
            etkin_siyasi=0,
            etkin_jeopolitik=0,
            kap1_siyasi=0,
            kritik_veto=False,
            veto_basliklari=[],
        )

    siyasi_sorgu = _sorgular("SIYASI_GOOGLE_SORGULARI", ['"kayyum atandı" belediye Türkiye'])
    jeo_sorgu = _sorgular("SAVAS_GOOGLE_SORGULARI", ["Hürmüz Boğazı İran"])

    siyasi, etkin_s, kap1_s, siyasi_veto_baslik = _sorgu_max_analiz(siyasi_sorgu, saat=pencere)
    jeo, etkin_j = _jeo_max_analiz(jeo_sorgu, saat=pencere)

    siyasi_veto = haberleri_analiz_et(siyasi_veto_baslik)
    veto = kritik_veto_aktif(siyasi_veto)
    veto_list = [b for b, _ in veto_basliklari(siyasi_veto)]

    return SentimentPaketi(
        siyasi=siyasi,
        jeopolitik=jeo,
        etkin_siyasi=etkin_s,
        etkin_jeopolitik=etkin_j,
        kap1_siyasi=kap1_s,
        kritik_veto=veto,
        veto_basliklari=veto_list[:5],
    )
