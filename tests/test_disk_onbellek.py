# -*- coding: utf-8 -*-
import os
import time

import pytest

import disk_onbellek
from disk_onbellek import disk_getir, disk_getir_aninda, disk_getir_swr, disk_sil, disk_yaz


@pytest.fixture(autouse=True)
def _temiz_anahtarlar():
    keys = ["t:swr1", "t:swr2", "t:swr3", "t:yazoku", "t:aninda1"]
    for k in keys:
        disk_sil(k)
    yield
    for k in keys:
        disk_sil(k)


def test_yaz_oku():
    disk_yaz("t:yazoku", {"a": 1})
    veri, yas = disk_getir("t:yazoku", ttl_sn=60)
    assert veri == {"a": 1}
    assert yas is not None and yas < 5


def test_swr_ilk_kullanim_senkron():
    sayac = {"n": 0}

    def uret():
        sayac["n"] += 1
        return "taze"

    assert disk_getir_swr("t:swr1", 60, uret) == "taze"
    assert sayac["n"] == 1
    # İkinci çağrı diskten — üretici çağrılmaz
    assert disk_getir_swr("t:swr1", 60, uret) == "taze"
    assert sayac["n"] == 1


def test_swr_bayat_veriyi_aninda_doner_arkada_tazeler():
    disk_yaz("t:swr2", "eski")
    # mtime'ı geriye çek — TTL dolmuş gibi
    yol = disk_onbellek._dosya("t:swr2")
    eski_zaman = time.time() - 3600
    os.utime(yol, (eski_zaman, eski_zaman))

    def uret():
        return "yeni"

    # Bayat ama max_bayat içinde: ESKİ değer anında döner
    sonuc = disk_getir_swr("t:swr2", ttl_sn=60, uret_fn=uret)
    assert sonuc == "eski"

    # Arka plan tazeleme kısa sürede diske "yeni" yazar
    for _ in range(50):
        time.sleep(0.05)
        veri, _ = disk_getir("t:swr2", ttl_sn=60)
        if veri == "yeni":
            break
    assert veri == "yeni"


def test_disk_getir_aninda_bekletmez():
    sayac = {"n": 0}

    def uret():
        sayac["n"] += 1
        time.sleep(5)
        return "taze"

    t0 = time.time()
    sonuc = disk_getir_aninda("t:aninda1", 60, uret, varsayilan="bos")
    assert time.time() - t0 < 1.0
    assert sonuc == "bos"


def test_portfoy_degerle_aninda():
    from macro_data import demo_snapshot
    from varlik_fiyat import portfoy_degerle
    from varliklarim import VarlikPortfoy, VarlikPozisyon

    snap = demo_snapshot()
    portfoy = VarlikPortfoy(
        id="p1", ad="Test", kaynak="test", olusturma="2026-01-01",
        pozisyonlar=[
            VarlikPozisyon(
                id="x", tur="hisse", sembol="THYAO.IS", ad="THY", miktar=10,
                maliyet=5000, alim_fiyati=500, para_birimi="TL", alim_tarihi="2026-01-01",
            ),
        ],
    )
    t0 = time.time()
    d = portfoy_degerle(portfoy, snap, aninda=True)
    assert time.time() - t0 < 3.0
    assert d.pozisyonlar


def test_swr_cok_bayat_senkron_tazeler():
    disk_yaz("t:swr3", "cok_eski")
    yol = disk_onbellek._dosya("t:swr3")
    eski_zaman = time.time() - 72 * 3600  # 72 saat — max_bayat (48s) aşıldı
    os.utime(yol, (eski_zaman, eski_zaman))

    sonuc = disk_getir_swr("t:swr3", ttl_sn=60, uret_fn=lambda: "yepyeni")
    assert sonuc == "yepyeni"
