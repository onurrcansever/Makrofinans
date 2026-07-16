# -*- coding: utf-8 -*-
import pandas as pd

from fiyat_para import (
    getiri_kur_ayarli,
    kaynak_para_birimi,
    pb_cevir,
    tablo_fiyat,
    tutar_goster,
)

EUR_TRY = 38.0
USD_TRY = 41.0


def _fx_serileri(eur_start=35.0, eur_end=38.0, usd_start=38.0, usd_end=41.0, n=30):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    eur = pd.Series([eur_start + (eur_end - eur_start) * i / (n - 1) for i in range(n)], index=idx)
    usd = pd.Series([usd_start + (usd_end - usd_start) * i / (n - 1) for i in range(n)], index=idx)
    return eur, usd


def test_kaynak_para_birimi_bist():
    assert kaynak_para_birimi("THYAO.IS", piyasa="BIST") == "TL"


def test_kaynak_para_birimi_etf_eur():
    assert kaynak_para_birimi("VWCE.DE", piyasa="ETF", varlik_turu="etf") == "EUR"


def test_kaynak_para_birimi_sp500():
    assert kaynak_para_birimi("AAPL", piyasa="SP500") == "USD"


def test_kaynak_para_birimi_nakit_ron():
    assert kaynak_para_birimi(pozisyon_turu="nakit_ron", varlik_turu="nakit_ron") == "TL"


def test_pb_cevir_roundtrip():
    tl = 3800.0
    eur = pb_cevir(tl, "TL", "EUR", EUR_TRY, USD_TRY)
    assert abs(pb_cevir(eur, "EUR", "TL", EUR_TRY, USD_TRY) - tl) < 0.01


def test_tablo_fiyat_bist_to_eur():
    v = tablo_fiyat(
        380.0, "EUR", EUR_TRY, USD_TRY,
        sembol="THYAO.IS", piyasa="BIST", quote_currency="TRY",
    )
    assert v == 10.0


def test_tutar_goster():
    assert tutar_goster(1000, "EUR", "TL", EUR_TRY, USD_TRY) == "38,000 TL"


def test_tutar_goster_eur_to_usd_requires_eur_usd():
    v = tutar_goster(1000, "EUR", "USD", EUR_TRY, USD_TRY, eur_usd=1.08)
    assert v == "1,080 USD"


def test_tefas_birim_pay_her_zaman_tl():
    v = tablo_fiyat(2.1019, "EUR", EUR_TRY, USD_TRY, kaynak_pb="TL")
    assert v == round(2.1019 / EUR_TRY, 4)


def test_getiri_usd_hisse_tl_alici():
    """USD hisse +10%, USDTRY +5% → TL alıcı ~+15.5%."""
    eur_s, usd_s = _fx_serileri(eur_start=35, eur_end=35, usd_start=40, usd_end=42, n=22)
    gbp_s = pd.Series([1.35] * 22, index=eur_s.index)
    bar_dates = usd_s.index
    r = getiri_kur_ayarli(10.0, "USD", "TL", 21, eur_s, usd_s, gbp_s, bar_dates=bar_dates)
    assert r is not None
    assert r > 14.0
    assert r < 17.0


def test_getiri_eur_hisse_eur_gosterim_degismez():
    eur_s, usd_s = _fx_serileri()
    r = getiri_kur_ayarli(-1.0, "EUR", "EUR", 21, eur_s, usd_s)
    assert r == -1.0


def test_getiri_tl_fon_eur_gosterim():
    """TL fon +5%; EUR/TRY düşerse (TL güçlenir) EUR bazında getiri daha yüksek."""
    eur_s, usd_s = _fx_serileri(eur_start=40, eur_end=38, n=31)
    gbp_s = pd.Series([1.35] * 31, index=eur_s.index)
    r = getiri_kur_ayarli(
        5.0, "TL", "EUR", 30, eur_s, usd_s, gbp_s, bar_dates=eur_s.index,
    )
    assert r is not None
    assert r > 5.0
