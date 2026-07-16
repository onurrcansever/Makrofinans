# -*- coding: utf-8 -*-
"""TEFAS getiri — fon PB → EUR; YLR akran bandı."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from investor_profile import YatirimProfili
from tefas_data import FonPerformans, TefasTaramaSonuc
from tefas_skor import (
    _fon_getiri_kaynak_pb,
    _ham_to_abs_norm,
    _mevduat_ayari,
    fonlari_skorla,
)


def _fx_rising_usd():
    """USDTRY yükselişi — yanlış TL-src EUR getiriyi şişirirdi."""
    idx = pd.date_range("2026-01-01", periods=220, freq="D")
    n = len(idx)
    eur = pd.Series([50.0 + i * 0.02 for i in range(n)], index=idx)
    usd = pd.Series([42.0 + i * 0.05 for i in range(n)], index=idx)
    return eur, usd


def _fon(kod, kat, g1a, *, para="TL", buyuk=5e9) -> FonPerformans:
    return FonPerformans(
        kod=kod, ad=kod, kisa_ad=kod, kategori=kat, kategori_etiket=kat,
        para_birimi=para, para_etiket=para, fiyat=2.0,
        getiri_1a=g1a, getiri_3a=g1a, getiri_ybb=g1a, fon_buyuklugu=buyuk,
    )


class TefasGetiriPbTest(unittest.TestCase):
    def test_ylr_kaynak_pb_usd(self):
        f = _fon("YLR", "para_piyasasi", 13.0, para="USD")
        self.assertEqual(_fon_getiri_kaynak_pb(f), "USD")

    def test_usd_getiri_not_treated_as_tl(self):
        """USD native 1A, yükselen USDTRY → TL-src EUR ≠ USD-src EUR."""
        from fiyat_para import tablo_getiri

        eur, usd = _fx_rising_usd()
        native = 12.0
        as_tl = tablo_getiri(native, "EUR", 30, eur, usd, asset_pb="TL", bar_dates=usd.index)
        as_usd = tablo_getiri(native, "EUR", 30, eur, usd, asset_pb="USD", bar_dates=usd.index)
        self.assertIsNotNone(as_tl)
        self.assertIsNotNone(as_usd)
        self.assertNotAlmostEqual(as_tl, as_usd, places=1)

    def test_ylr_skor_peer_band(self):
        """YLR (USD) kısa vade — +4 mevduat yok; skor eski 88'den düşük, akran bandına yakın."""
        # Sakin FX (EURUSD ~ sabit) — kur şişmesi olmadan fon PB→EUR
        idx = pd.date_range("2026-01-01", periods=220, freq="D")
        eur = pd.Series(53.5, index=idx)
        usd = pd.Series(46.5, index=idx)
        ylr = _fon("YLR", "para_piyasasi", 11.0, para="USD", buyuk=11_000)
        pkt = _fon("PKT", "para_piyasasi", 3.3, para="TL", buyuk=5e9)
        ypt = _fon("YPT", "para_piyasasi", 3.2, para="TL", buyuk=5e9)
        ksy = _fon("KSY", "para_piyasasi", 3.4, para="TL", buyuk=3e9)
        mev = SimpleNamespace(
            oranlar=[
                SimpleNamespace(vade="USD mevduat", net_yillik=0.015),
                SimpleNamespace(vade="EUR mevduat", net_yillik=0.01),
            ],
            eur_mevduat_net=1.0,
            profil_vade_net=24.0,  # ~%2 / ay — PP fonları cezalandırmasın
            profil_vade_reel=-3.0,
        )
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[ylr, pkt, ypt, ksy]),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            rejim="NOTR",
            mevduat_reel=-3.0,
            gosterim_pb="EUR",
            eur_seri=eur,
            usd_seri=usd,
            mevduat_ozet=mev,
        )
        by = {f.kod: f for f in sonuc.fonlar}
        self.assertEqual(by["YLR"].skor_faktorler.get("mevduat"), 0.0)
        peers = [by["PKT"].skor, by["YPT"].skor, by["KSY"].skor]
        peer_avg = sum(peers) / len(peers)
        # Eski bug: ~88 vs ~78; hedef: 79–82, akran farkı küçük
        self.assertLess(by["YLR"].skor, 85.0)
        self.assertGreaterEqual(by["YLR"].skor, 74.0)
        self.assertLess(abs(by["YLR"].skor - peer_avg), 8.0, msg=(
            f"YLR={by['YLR'].skor} peers={peers} avg={peer_avg:.1f} "
            f"fac={by['YLR'].skor_faktorler} 1A={by['YLR'].getiri_gosterim_1a}"
        ))
        self.assertTrue(74.0 <= by["YLR"].skor <= 84.0)

    def test_mevduat_bonus_tl_only(self):
        tl = _fon("PKT", "para_piyasasi", 5.0, para="TL")
        usd = _fon("YLR", "para_piyasasi", 5.0, para="USD")
        mev = SimpleNamespace(
            oranlar=[SimpleNamespace(vade="USD mevduat", net_yillik=0.012)],
            eur_mevduat_net=1.0,
            profil_vade_net=36.0,
        )
        adj_tl, _ = _mevduat_ayari(tl, mevduat_reel=None, mevduat_ozet=mev)
        adj_usd, _ = _mevduat_ayari(usd, mevduat_reel=None, mevduat_ozet=mev)
        self.assertEqual(adj_tl, 4.0)  # 5 >= 36/12 + 2
        self.assertEqual(adj_usd, 0.0)  # USD fon +4 ikramiye almaz


if __name__ == "__main__":
    unittest.main()
