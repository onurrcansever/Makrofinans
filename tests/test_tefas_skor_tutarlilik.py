# -*- coding: utf-8 -*-
"""TEFAS skor tutarlılık — görünen getiri ile öneri çelişmemeli."""
import unittest

import pandas as pd

from investor_profile import YatirimProfili
from tefas_data import FonPerformans, TefasTaramaSonuc
from tefas_skor import (
    assert_tefas_skor_tutarliligi,
    fonlari_skorla,
)


def _flat_fx():
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    return pd.Series(38.0, index=idx), pd.Series(41.0, index=idx)


def _fon(
    kod, kat, g1a, g3a, gybb, *, para="TL", buyuk=1e9,
) -> FonPerformans:
    return FonPerformans(
        kod=kod,
        ad=kod,
        kisa_ad=kod,
        kategori=kat,
        kategori_etiket=kat,
        para_birimi=para,
        para_etiket=para,
        fiyat=1.7,
        getiri_1a=g1a,
        getiri_3a=g3a,
        getiri_ybb=gybb,
        fon_buyuklugu=buyuk,
    )


class TefasSkorTutarlilikTest(unittest.TestCase):
    def test_pys_yoa_not_al_when_returns_negative_yrl_ranks_higher(self):
        """PYS/YOA negatif getiri → AL olmamalı; YLR en yüksek skoru almalı."""
        pp_neg = [
            _fon(f"PP{i}", "para_piyasasi", -0.5, -3.5, -5.5)
            for i in range(8)
        ]
        pys = _fon("PYS", "serbest_doviz", 0.1, -3.93, -6.29, para="USD")
        yoa = _fon("YOA", "serbest_doviz", 0.04, -3.98, -6.34, para="USD")
        ylr = _fon("YLR", "para_piyasasi", 13.48, 8.92, 6.24, buyuk=5e9)
        eur, usd = _flat_fx()
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=pp_neg + [pys, yoa, ylr]),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            rejim="NOTR",
            gosterim_pb="USD",
            eur_seri=eur,
            usd_seri=usd,
        )
        by_kod = {f.kod: f for f in sonuc.fonlar}
        self.assertNotEqual(by_kod["PYS"].oneri, "AL")
        self.assertNotEqual(by_kod["YOA"].oneri, "AL")
        self.assertLess(by_kod["PYS"].skor, by_kod["YLR"].skor)
        self.assertLess(by_kod["YOA"].skor, by_kod["YLR"].skor)
        self.assertTrue(by_kod["PYS"].akran_kucuk)
        assert_tefas_skor_tutarliligi(sonuc.fonlar)

    def test_skor_100_saturation_guard(self):
        """Tam 100 + AL birlikte olamaz (doyum kontrolü)."""
        fonlar = [
            _fon("A", "para_piyasasi", -1, -2, -3),
            _fon("B", "para_piyasasi", -1.5, -2.5, -4),
        ]
        eur, usd = _flat_fx()
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=fonlar),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            gosterim_pb="USD",
            eur_seri=eur,
            usd_seri=usd,
        )
        for f in sonuc.fonlar:
            self.assertLess(f.skor, 100.0)
        assert_tefas_skor_tutarliligi(sonuc.fonlar)

    def test_skor_uses_display_pb_not_tl_only(self):
        """TL pozitif ama USD negatif senaryoda skor USD'yi yansıtmalı."""
        f = _fon("X", "para_piyasasi", 5.0, 4.0, 3.0)
        idx = pd.date_range("2025-01-01", periods=400, freq="D")
        eur = pd.Series([38.0 + i * 0.05 for i in range(400)], index=idx)
        usd = pd.Series([41.0 + i * 0.08 for i in range(400)], index=idx)
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=[f]),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            gosterim_pb="USD",
            eur_seri=eur,
            usd_seri=usd,
        )
        scored = sonuc.fonlar[0]
        self.assertEqual(scored.skor_pb, "USD")
        self.assertIsNotNone(scored.getiri_gosterim_3a)
        self.assertNotAlmostEqual(scored.getiri_gosterim_3a, 4.0, places=0)

    def test_ylr_ybb_felaket_not_al_or_top(self):
        """1A pozitif + YBB −95 (Fintables YLR) → AL/İZLE yok, listenin başında olmamalı."""
        peers = [
            _fon(f"PP{i}", "para_piyasasi", 3.2, 3.0, 8.0, buyuk=2e9)
            for i in range(4)
        ]
        ylr = _fon(
            "YLR", "para_piyasasi", 14.7, -3.0, -95.0,
            para="USD", buyuk=11_000,
        )
        eur, usd = _flat_fx()
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=peers + [ylr]),
            YatirimProfili(risk="dusuk", vade="kisa_3"),
            rejim="NOTR",
            gosterim_pb="EUR",
            eur_seri=eur,
            usd_seri=usd,
        )
        by = {f.kod: f for f in sonuc.fonlar}
        self.assertNotIn(by["YLR"].oneri, ("AL", "IZLE"))
        self.assertLess(by["YLR"].skor, 52.0)
        self.assertNotEqual(sonuc.fonlar[0].kod, "YLR")
        self.assertIn("felaket", (by["YLR"].skor_notu or "").lower())
        assert_tefas_skor_tutarliligi(sonuc.fonlar)

    def test_kriz_blocks_risk_al_allows_para_piyasasi(self):
        """KRIZ: hisse AL/İZLE yok; para piyasası AL istisnası."""
        hisse = [
            _fon(f"H{i}", "hisse", 8.0, 12.0, 20.0, buyuk=3e9)
            for i in range(4)
        ]
        pp = [
            _fon(f"P{i}", "para_piyasasi", 3.5, 4.0, 9.0, buyuk=5e9)
            for i in range(4)
        ]
        eur, usd = _flat_fx()
        sonuc = fonlari_skorla(
            TefasTaramaSonuc(fonlar=hisse + pp),
            YatirimProfili(risk="yuksek", vade="orta"),
            rejim="KRIZ",
            gosterim_pb="TL",
            eur_seri=eur,
            usd_seri=usd,
        )
        by = {f.kod: f for f in sonuc.fonlar}
        for i in range(4):
            self.assertNotIn(by[f"H{i}"].oneri, ("AL", "IZLE"), by[f"H{i}"].skor_notu)
        assert_tefas_skor_tutarliligi(sonuc.fonlar, rejim="KRIZ")


if __name__ == "__main__":
    unittest.main()
