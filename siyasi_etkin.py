# -*- coding: utf-8 -*-
"""Kapı 1 siyasi sayım — duygu şişirmesi tek başına kriz tetiklemesin."""
from __future__ import annotations

from siyasi_esik import esikler


def kap1_haber_sayisi(raw: int, etkin: int) -> int:
    """
    Kapı 1 sayımı — kriz eşiği altında yalnızca ham sayı.
    Duygu şişirmesi ancak ham zaten kriz bandındaysa uygulanır.
    """
    raw = max(0, int(raw or 0))
    etkin = max(0, int(etkin or 0))
    es = esikler()
    if raw < es["kriz"]:
        return raw
    return etkin


def siyasi_kriz_mi(raw: int, etkin: int) -> bool:
    """Kriz yalnızca ham sayı kriz eşiğini geçince."""
    es = esikler()
    raw = max(0, int(raw or 0))
    return raw >= es["kriz"]


def siyasi_sayim_raporla(snap, sentiment) -> int:
    """
    Özet tablo ile 4 kapı detayında aynı Kapı 1 sayımını kullan.
    Ham GDELT sayısı kaynak satırında not olarak kalır.
    """
    import config

    raw = (
        sentiment.siyasi.haber_sayisi
        if sentiment and sentiment.siyasi.haber_sayisi
        else snap.veri.siyasi_risk_makale_sayisi
    ) or 0
    etkin = sentiment.etkin_siyasi if sentiment else raw
    kap1 = (
        sentiment.kap1_siyasi
        if sentiment and sentiment.kap1_siyasi
        else kap1_haber_sayisi(raw, etkin)
    )
    ham_gdelt = snap.veri.siyasi_risk_makale_sayisi
    snap.veri.siyasi_risk_makale_sayisi = kap1
    kh = dict(snap.kaynak_haritasi or {})
    notu = f"Kapı 1 sayımı {kap1} haber ({config.SIYASI_RISK_TARAMA_SAAT}s duygu taraması)"
    if ham_gdelt is not None and int(ham_gdelt) != int(kap1):
        notu += f" · ham GDELT {ham_gdelt}"
    kh["siyasi_risk"] = notu
    snap.kaynak_haritasi = kh
    from siyasi_esik import baseline_guncelle
    baseline_guncelle(kap1)
    return kap1
