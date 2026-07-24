# -*- coding: utf-8 -*-
from tefas_stopaj import (
    DONEM_202411,
    DONEM_YENI,
    STOPAJ_CAPTION,
    tefas_stopaj_sinifi,
)


def test_hisse_yogun_sifir():
    etiket, oran, not_ = tefas_stopaj_sinifi(
        ad="KUVEYT TÜRK PORTFÖY KATILIM HİSSE SENEDİ (TL) FONU (HİSSE SENEDİ YOĞUN FON)",
        kategori="hisse",
    )
    assert oran == 0.0
    assert etiket.startswith("%0")
    assert "hisse" in not_.lower() or "Hisse" in not_


def test_pp_yeni_iktisap_175():
    etiket, oran, not_ = tefas_stopaj_sinifi(
        ad="YAPI KREDİ PORTFÖY PARA PİYASASI FONU",
        kategori="para_piyasasi",
        iktisap_donemi=DONEM_YENI,
    )
    assert oran == 17.5
    assert "17,5" in etiket or "17.5" in etiket
    assert "?" not in etiket
    assert "iktisap" in not_.lower() or "matris" in not_.lower()


def test_altin_yeni_175():
    _, oran, _ = tefas_stopaj_sinifi(
        ad="KUVEYT TÜRK PORTFÖY ALTIN KATILIM FONU",
        kategori="altin_emtia",
    )
    assert oran == 17.5


def test_eski_dilim_pp():
    etiket, oran, _ = tefas_stopaj_sinifi(
        ad="YAPI KREDİ PORTFÖY PARA PİYASASI FONU",
        kategori="para_piyasasi",
        iktisap_donemi=DONEM_202411,
    )
    assert oran == 10.0
    assert "10" in etiket
    assert "iktisap" in etiket.lower()


def test_doviz_serbest_175():
    etiket, oran, not_ = tefas_stopaj_sinifi(
        ad="KUVEYT TÜRK PORTFÖY ALTINCI KATILIM SERBEST (DÖVİZ-AVRO) FON",
        kategori="serbest_doviz",
    )
    assert oran == 17.5
    assert "?" not in etiket
    assert "döviz" in not_.lower() or "Döviz" in not_


def test_caption_brut():
    assert "brüt" in STOPAJ_CAPTION.lower() or "brüttür" in STOPAJ_CAPTION
