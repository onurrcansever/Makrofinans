# -*- coding: utf-8 -*-
from unittest.mock import patch

import tefas_fon_meta as m


def test_parse_tr_float():
    assert m._parse_tr_float("1,48") == 1.48
    assert m._parse_tr_float("0,3") == 0.3
    assert m._parse_tr_float("") is None


def test_parse_kap_fon_sayfasi_yonetim():
    html = r'{\"uygulananYonetimUcretiOranYillikYuzde\":\"1,48\",\"x\":1}'
    parsed = m._parse_kap_fon_sayfasi(html)
    assert parsed["yonetim"] == 1.48


def test_parse_kap_tgo_bildirim():
    html = (
        "Yıllık Azami Fon Toplam Gider Oranı (%)"
        r"\u003e%\u00a03,65\u003c"
        "Dönem Sonu İtibariyle Gerçekleşen Fon Toplam Gider Oranı (%)"
        r"\u00a01,81"
    )
    # Pattern expects %\u00a0 immediately after label window — build clearer fixture
    html = (
        "Yıllık Azami Fon Toplam Gider Oranı"
        + "xxxx"
        + r"%\u00a03,65"
        + "yyyy"
        + "Dönem Sonu İtibariyle Gerçekleşen Fon Toplam Gider Oranı"
        + "zzzz"
        + r"%\u00a01,81"
    )
    tgo = m._parse_kap_tgo_bildirim(html)
    assert tgo["tgo_azami"] == 3.65
    assert tgo["tgo_gerceklesen"] == 1.81


def test_tgo_gosterim_tercih_azami():
    meta = m.FonGiderMeta(kod="YLB", tgo_azami_pct=3.65, tgo_gerceklesen_pct=0.31)
    assert m.tgo_gosterim_pct(meta) == 3.65
    meta2 = m.FonGiderMeta(kod="YLB", tgo_gerceklesen_pct=0.31)
    assert m.tgo_gosterim_pct(meta2) == 0.31


def test_fon_gider_meta_cek_tek_mock():
    kap_html = r'{\"uygulananYonetimUcretiOranYillikYuzde\":\"1,48\"}'
    with patch.object(m, "tefas_kap_link", return_value="https://www.kap.org.tr/tr/fon/ylb"), \
         patch.object(m, "_http_text", return_value=kap_html), \
         patch("disk_onbellek.disk_getir", return_value=(None, None)), \
         patch("disk_onbellek.disk_yaz"):
        meta = m.fon_gider_meta_cek_tek("YLB", zorla=True)
    assert meta.yonetim_ucreti_yillik_pct == 1.48
    assert "KAP" in meta.kaynak or "TEFAS" in meta.kaynak


def test_bos_kod():
    meta = m.fon_gider_meta_cek_tek("", zorla=True)
    assert meta.yonetim_ucreti_yillik_pct is None


def test_bildirim_id_aria_label():
    html = (
        r'href=\"/tr/Bildirim/1628436\",\"aria-label\":\"Fon Toplam Gider Oranı '
        r've Fon Toplam Giderinin Dağılımı bağlantısı\"'
    )
    assert m._bildirim_id_from_kap(html) == "1628436"


def test_bos_cache_yeniden_dener():
    bos = {"kod": "PKT", "yonetim_ucreti_yillik_pct": None, "tgo_azami_pct": None,
           "tgo_gerceklesen_pct": None, "kaynak": "", "guncelleme": "", "kap_link": ""}
    kap_html = r'{\"uygulananYonetimUcretiOranYillikYuzde\":\"0,6\"}'
    with patch.object(m, "tefas_kap_link", return_value="https://kap/pkt"), \
         patch.object(m, "_http_text", return_value=kap_html), \
         patch("disk_onbellek.disk_getir", return_value=(bos, 10.0)), \
         patch("disk_onbellek.disk_yaz") as yaz:
        meta = m.fon_gider_meta_cek_tek("PKT", zorla=False)
    assert meta.yonetim_ucreti_yillik_pct == 0.6
    yaz.assert_called()
