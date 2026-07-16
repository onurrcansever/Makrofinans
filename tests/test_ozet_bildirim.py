# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from macro_data import demo_snapshot
from ozet_bildirim import ozet_metni_olustur


def _h(sembol, ad, skor=80, uygun="UYGUN", piyasa="BIST", tur="hisse", sinyal="BEKLE"):
    return SimpleNamespace(
        sembol=sembol,
        ad=ad,
        skor=skor,
        alim_uygun=uygun,
        piyasa=piyasa,
        varlik_turu=tur,
        sinyal=sinyal,
        fiyat=1.0,
        signal_v2_decision="AL" if uygun == "UYGUN" else "BEKLE",
        signal_v2_percentile=85.0,
    )


def test_ozet_metni_kisa_format():
    tahsis = SimpleNamespace(
        rejim=SimpleNamespace(etiket="Enflasyon koruma"),
        agirliklar={"eur_cash": 0.42, "tl_deposit": 0.18, "gold": 0.15, "bist": 0.05},
        tl_tavan_oran=0.12,
    )
    profil = SimpleNamespace(ozet=lambda: "Orta risk · 0–6 ay")
    tarama = SimpleNamespace(
        hisseler=[
            _h("HALKB.IS", "Halkbank"),
            _h("CSPX.L", "CSPX", piyasa="ETF", tur="etf"),
        ]
    )
    olaylar = [("AL", "HALKB.IS", _h("HALKB.IS", "Halkbank"))]

    with patch(
        "ozet_bildirim._varlik_satirlari",
        return_value=["VARLIKLAR: 920.000 TL (+0,5% önceki taramaya göre)", " K/Z: +12.000 TL (+1,3%)"],
    ):
        metin = ozet_metni_olustur(
            tahsis,
            profil,
            tarama,
            olaylar,
            rejim_degisti=False,
            onceki_rejim={"rejim_etiket": "Enflasyon koruma"},
            onceki_tl=900_000.0,
            snap=demo_snapshot(),
        )

    assert "MAKROFINANS" in metin
    assert "REJİM: Enflasyon koruma" in metin
    assert "VARLIKLAR:" in metin
    assert "+AL hisse: HALKB" in metin
    assert "GÜNCEL AL:" in metin
    assert "HALKB" in metin
    assert "CSPX" in metin
    assert "Toplam 2 AL" in metin
    assert "Tahsis:" in metin
    assert "Dashboard" not in metin
    assert len(metin) < 1200


@patch("ozet_bildirim.bildirim_gonder", return_value=True)
@patch("ozet_bildirim._portfoy_tl", return_value=950_000.0)
@patch("ozet_bildirim.tarama_yap")
def test_kontrol_ozet_sadece_degisimde_gonder(mock_tarama, _ptl, mock_gonder):
    from investor_profile import YatirimProfili
    from ozet_bildirim import kontrol_ozet_ve_bildir

    h = _h("HALKB.IS", "Halkbank")
    tahsis = SimpleNamespace(
        rejim=SimpleNamespace(rejim="enflasyon_koruma", etiket="Enflasyon koruma"),
        agirliklar={"eur_cash": 0.4},
        tl_tavan_oran=0.1,
    )
    tarama = SimpleNamespace(hisseler=[h])
    mock_tarama.return_value = (tahsis, tarama, YatirimProfili(risk="orta", vade="kisa_6"))

    with patch("ozet_bildirim.rejim_oku", return_value={"rejim": "enflasyon_koruma", "rejim_etiket": "Enflasyon koruma"}), \
         patch("ozet_bildirim.rejim_degisti_mi", return_value=False), \
         patch("ozet_bildirim.sinyal_oku", return_value={"HALKB.IS": {"karar": "IZLE"}}), \
         patch("ozet_bildirim.rejim_yaz"), patch("ozet_bildirim.sinyal_yaz"), patch("ozet_bildirim._ozet_yaz"), \
         patch("ozet_bildirim._varlik_satirlari", return_value=["VARLIKLAR: 920.000 TL"]):
        ok, olaylar, rejim_degisti = kontrol_ozet_ve_bildir(
            demo_snapshot(), bildir=True, her_zaman=False
        )
        assert ok is True
        assert len(olaylar) == 1
        assert rejim_degisti is False
        mock_gonder.assert_called_once()


@patch("ozet_bildirim.bildirim_gonder", return_value=True)
@patch("ozet_bildirim._portfoy_tl", return_value=950_000.0)
@patch("ozet_bildirim.tarama_yap")
def test_kontrol_ozet_her_zaman_degisim_yokken_gonder(mock_tarama, _ptl, mock_gonder):
    from investor_profile import YatirimProfili
    from ozet_bildirim import kontrol_ozet_ve_bildir

    h = _h("HALKB.IS", "Halkbank", uygun="IZLE")
    tahsis = SimpleNamespace(
        rejim=SimpleNamespace(rejim="enflasyon_koruma", etiket="Enflasyon koruma"),
        agirliklar={"eur_cash": 0.4},
        tl_tavan_oran=0.1,
    )
    tarama = SimpleNamespace(hisseler=[h])
    mock_tarama.return_value = (tahsis, tarama, YatirimProfili(risk="orta", vade="kisa_6"))

    with patch("ozet_bildirim.rejim_oku", return_value={"rejim": "enflasyon_koruma", "rejim_etiket": "Enflasyon koruma"}), \
         patch("ozet_bildirim.rejim_degisti_mi", return_value=False), \
         patch("ozet_bildirim.sinyal_oku", return_value={"HALKB.IS": {"karar": "IZLE"}}), \
         patch("ozet_bildirim.rejim_yaz"), patch("ozet_bildirim.sinyal_yaz"), patch("ozet_bildirim._ozet_yaz"), \
         patch("ozet_bildirim._varlik_satirlari", return_value=["VARLIKLAR: 920.000 TL"]):
        ok, olaylar, rejim_degisti = kontrol_ozet_ve_bildir(
            demo_snapshot(), bildir=True, her_zaman=True
        )
        assert ok is True
        assert olaylar == []
        assert rejim_degisti is False
        mock_gonder.assert_called_once()
        assert "değişiklik yok" in mock_gonder.call_args[0][0]
