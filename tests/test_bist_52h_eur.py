# -*- coding: utf-8 -*-
"""BIST EUR bazlı 52H band pozisyonu — birim testler."""
from __future__ import annotations

import pandas as pd
import pytest

from bist_52h_eur import (
    MIN_52H_GUN,
    band_pozisyon_0_100,
    bist_52h_eur_hesapla,
    degerleme_52h_pozisyon,
    format_52h_metin,
)
from stock_scanner import HisseAnaliz


def _gun_serisi(n: int, baslangic: float, bitis: float) -> pd.Series:
    idx = pd.bdate_range("2024-01-02", periods=n)
    vals = [baslangic + (bitis - baslangic) * i / (n - 1) for i in range(n)]
    return pd.Series(vals, index=idx)


def _hisse(**kw) -> HisseAnaliz:
    defaults = dict(
        sembol="TEST.IS",
        ad="Test",
        piyasa="BIST",
        fiyat=100.0,
        degisim_1g=0.0,
        degisim_1ay=0.0,
        degisim_3ay=0.0,
        rsi=50.0,
        sma20=100.0,
        sma50=100.0,
        sinyal="BEKLE",
        skor=50.0,
        gerekce="",
    )
    defaults.update(kw)
    return HisseAnaliz(**defaults)


def test_enflasyon_senaryosu_eur_duz_tl_zirvede():
    """Hisse +28%, kur +28% → EUR sabit; TL band tepesinde, EUR pozisyonu düşük/None."""
    n = MIN_52H_GUN
    tl = _gun_serisi(n, 100.0, 128.0)
    kur = _gun_serisi(n, 30.0, 38.4)
    sonuc = bist_52h_eur_hesapla(tl, kur)
    assert sonuc.join_gun >= MIN_52H_GUN
    assert sonuc.eur_pozisyon_pct is None or sonuc.eur_pozisyon_pct <= 50.0
    tl_poz = band_pozisyon_0_100(tl, pencere=n)
    assert tl_poz is not None and tl_poz >= 95.0


def test_kur_hizli_hisse_yavas_eur_tl_altinda():
    """Hisse +28%, kur +35% → EUR cinsinden değer kaybı; TL band tepesinde."""
    n = MIN_52H_GUN
    tl = _gun_serisi(n, 100.0, 128.0)
    kur = _gun_serisi(n, 35.0, 47.25)
    sonuc = bist_52h_eur_hesapla(tl, kur)
    tl_poz = band_pozisyon_0_100(tl, pencere=n)
    assert tl_poz is not None and tl_poz >= 95.0
    assert sonuc.eur_pozisyon_pct is not None
    assert sonuc.eur_pozisyon_pct < tl_poz - 10


def test_inner_join_ffill_yok():
    """Kur serisinde eksik gün — inner join, ffill yok."""
    n = MIN_52H_GUN + 10
    tl = _gun_serisi(n, 50.0, 60.0)
    kur = _gun_serisi(n, 30.0, 33.0)
    kur = kur.drop(kur.index[100:105])
    sonuc = bist_52h_eur_hesapla(tl, kur)
    assert sonuc.join_gun == n - 5


def test_yetersiz_veri_etiketi():
    tl = _gun_serisi(100, 10.0, 12.0)
    kur = _gun_serisi(100, 30.0, 31.0)
    sonuc = bist_52h_eur_hesapla(tl, kur)
    assert sonuc.etiket == "yetersiz veri"
    assert sonuc.eur_pozisyon_pct is None


def test_max_eq_min_pozisyon_none():
    seri = pd.Series([3.5] * MIN_52H_GUN, index=pd.bdate_range("2024-01-02", periods=MIN_52H_GUN))
    assert band_pozisyon_0_100(seri) is None


def test_degerleme_bist_eur_kullanir():
    h = _hisse(zirve_52h_pct=97.0, zirve_52h_eur_pct=55.0)
    assert degerleme_52h_pozisyon(h) == 55.0


def test_degerleme_bist_yetersiz_nominal_kullanmaz():
    h = _hisse(zirve_52h_pct=97.0, zirve_52h_eur_etiket="yetersiz veri")
    assert degerleme_52h_pozisyon(h) is None


def test_degerleme_abd_nominal():
    h = _hisse(sembol="AAPL", piyasa="NASDAQ", zirve_52h_pct=88.0)
    assert degerleme_52h_pozisyon(h) == 88.0


def test_format_52h_metin_bist():
    h = _hisse(zirve_52h_pct=97.0, zirve_52h_eur_pct=71.0)
    assert format_52h_metin(h) == "52H %97 (TL) · %71 (EUR)"


def test_format_52h_metin_abd():
    h = _hisse(sembol="SPY", piyasa="ETF", zirve_52h_pct=85.0)
    assert format_52h_metin(h) == "52H %85"
