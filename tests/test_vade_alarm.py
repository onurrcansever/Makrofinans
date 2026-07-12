# -*- coding: utf-8 -*-
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from ozet_bildirim import _vade_olaylari


def _vb(poz_id="mev1", kalan_gun=5, anapara=1_200_000.0, net=1_310_000.0, banka="Yapı Kredi"):
    return SimpleNamespace(
        pozisyon=SimpleNamespace(id=poz_id, banka=banka),
        kalan_gun=kalan_gun,
        vade_tarihi=date.today() + timedelta(days=kalan_gun),
        anapara_tl=anapara,
        net_tl=net,
        brut_faiz_tl=130_000.0,
        stopaj_tl=20_000.0,
    )


def test_7_gun_kala_uyari_uretilir():
    with patch("nakit_danisman.vadeli_mevduatlar", return_value=[_vb(kalan_gun=5)]):
        satirlar, yeni = _vade_olaylari({})
    assert len(satirlar) == 1
    assert "vadeye 5 gün" in satirlar[0]
    assert "Yapı Kredi" in satirlar[0]
    assert yeni == {"mev1": "7gun"}


def test_ayni_asama_tekrar_bildirilmez():
    with patch("nakit_danisman.vadeli_mevduatlar", return_value=[_vb(kalan_gun=5)]):
        satirlar, yeni = _vade_olaylari({"mev1": "7gun"})
    assert satirlar == []
    assert yeni == {"mev1": "7gun"}


def test_vade_gunu_ayri_uyari():
    # 7 gün uyarısı gitmişti; vade dolunca yeni aşama bildirilir
    with patch("nakit_danisman.vadeli_mevduatlar", return_value=[_vb(kalan_gun=0)]):
        satirlar, yeni = _vade_olaylari({"mev1": "7gun"})
    assert len(satirlar) == 1
    assert "VADE DOLDU" in satirlar[0]
    assert yeni == {"mev1": "vade"}


def test_vade_asamasi_sonrasi_sessiz():
    with patch("nakit_danisman.vadeli_mevduatlar", return_value=[_vb(kalan_gun=-3)]):
        satirlar, yeni = _vade_olaylari({"mev1": "vade"})
    assert satirlar == []


def test_uzak_vade_bildirilmez():
    with patch("nakit_danisman.vadeli_mevduatlar", return_value=[_vb(kalan_gun=60)]):
        satirlar, yeni = _vade_olaylari({})
    assert satirlar == []
    assert yeni == {}
