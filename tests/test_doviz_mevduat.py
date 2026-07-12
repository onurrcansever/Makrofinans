# -*- coding: utf-8 -*-
"""Yapı Kredi döviz mevduat faizinin canlı çekimi ve mevduat tablosuna akışı."""
from unittest.mock import patch

import pytest

import yapikredi_rates
from disk_onbellek import disk_sil
from yapikredi_rates import YapikrediDovizMevduat, yapikredi_doviz_faizleri


@pytest.fixture(autouse=True)
def _temiz():
    disk_sil("ykb:doviz_mevduat")
    yapikredi_rates._DOVIZ_CACHE["ts"] = 0.0
    yapikredi_rates._DOVIZ_CACHE["data"] = None
    yield
    disk_sil("ykb:doviz_mevduat")
    yapikredi_rates._DOVIZ_CACHE["ts"] = 0.0
    yapikredi_rates._DOVIZ_CACHE["data"] = None


def test_doviz_faizleri_canli():
    with patch.object(yapikredi_rates, "_doviz_tek", side_effect=lambda dv, gun=365: {"USD": 0.01, "EUR": 0.01}[dv]):
        d = yapikredi_doviz_faizleri(cache_kullan=False)
    assert d is not None
    assert d.usd_1y_brut == 0.01
    assert d.eur_1y_brut == 0.01
    assert "Yapı Kredi" in d.kaynak


def test_doviz_faizleri_hepsi_basarisiz_none():
    with patch.object(yapikredi_rates, "_doviz_tek", return_value=None):
        d = yapikredi_doviz_faizleri(cache_kullan=False)
    assert d is None


def test_mevduat_tablosu_canli_oran_kullanir():
    from rates_tr import mevduat_analizi

    sahte = YapikrediDovizMevduat(
        usd_1y_brut=0.01,
        eur_1y_brut=0.01,
        kaynak="Yapı Kredi canlı (test)",
        cekim_zamani="2026-07-09 23:00",
    )
    with patch("yapikredi_rates.yapikredi_doviz_faizleri", return_value=sahte):
        a = mevduat_analizi(35.0, profil_vade="TL 3 ay", eur_try=48.0, kalan_gun=90)

    eur = next(o for o in a.oranlar if o.vade == "EUR mevduat")
    usd = next(o for o in a.oranlar if o.vade == "USD mevduat")
    # %0,01 brüt → ondalık 0.0001; net = brüt × (1 − stopaj %25)
    assert eur.brut_yillik == pytest.approx(0.0001)
    assert eur.net_yillik == pytest.approx(0.000075)
    assert usd.brut_yillik == pytest.approx(0.0001)
    assert "canlı" in eur.kaynak


def test_mevduat_tablosu_ykb_yoksa_env_yedegi():
    from rates_tr import mevduat_analizi

    with patch("yapikredi_rates.yapikredi_doviz_faizleri", return_value=None):
        a = mevduat_analizi(35.0, profil_vade="TL 3 ay", eur_try=48.0, kalan_gun=90)

    eur = next(o for o in a.oranlar if o.vade == "EUR mevduat")
    assert "Yedek varsayım" in eur.kaynak
