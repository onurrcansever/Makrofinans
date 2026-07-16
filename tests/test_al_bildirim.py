# -*- coding: utf-8 -*-
from types import SimpleNamespace

from al_bildirim import guncel_al_satirlar


def _h(sembol, skor=80, piyasa="BIST", tur="hisse", karar="AL"):
    return SimpleNamespace(
        sembol=sembol,
        ad=sembol,
        skor=skor,
        alim_uygun="UYGUN",
        piyasa=piyasa,
        varlik_turu=tur,
        fiyat=1.0,
        signal_v2_decision=karar,
        signal_v2_percentile=90.0,
    )


def test_guncel_al_tum_adaylar():
    hisseler = [_h(f"H{i}.IS", skor=70 + i) for i in range(8)]
    hisseler += [_h("CSPX.L", skor=85, piyasa="ETF", tur="etf", karar="GÜÇLÜ AL")]
    satirlar = guncel_al_satirlar(hisseler)
    metin = "\n".join(satirlar)
    assert "Toplam 9 AL" in metin
    assert "8 hisse" in metin
    for i in range(8):
        assert f"H{i}" in metin
    assert "CSPX" in metin
    assert "GÜÇLÜ AL" in metin
