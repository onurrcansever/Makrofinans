# -*- coding: utf-8 -*-
"""Tek hisse AL hikâye filtresi testleri."""
import unittest

from alim_uygunluk import alim_aksiyon_hucre, alim_uygunluk_uygula, _hikaye_al_kontrol
from stock_scanner import HisseAnaliz


def _bist(**kw):
    base = dict(
        sembol="DOAS.IS",
        ad="Dogus Otomotiv",
        piyasa="BIST",
        fiyat=182.0,
        degisim_1g=-1.1,
        degisim_1ay=-4.4,
        degisim_3ay=3.2,
        degisim_1y=15.0,
        rsi=42.0,
        sma20=185.0,
        sma50=180.0,
        sinyal="BEKLE",
        skor=89.0,
        gerekce="test",
        sektor="tuketim",
        teknik_skor=75.0,
        temel_skor=98.0,
        bilesik_skor=89.0,
        sma200=184.0,
        zirve_52h_pct=81.0,
        endeks_gore=-5.0,
    )
    base.update(kw)
    return HisseAnaliz(**base)


class HikayeAlFiltreTest(unittest.TestCase):
    def test_doas_benzeri_al_olmaz(self):
        h = _bist()
        ok, engel = _hikaye_al_kontrol(h)
        self.assertFalse(ok)
        self.assertTrue(any("teknik teyit" in e for e in engel))
        self.assertTrue(any("52H" in e for e in engel))
        self.assertTrue(any("SMA200" in e for e in engel))

        alim_uygunluk_uygula([h], {h.sembol}, 60)
        self.assertNotEqual(alim_aksiyon_hucre(h), "AL")

    def test_trend_teyitli_gecer(self):
        h = _bist(
            sinyal="TREND_ALIM",
            fiyat=190.0,
            sma200=180.0,
            zirve_52h_pct=68.0,
            degisim_1ay=2.0,
            degisim_3ay=8.0,
            endeks_gore=3.0,
        )
        ok, engel = _hikaye_al_kontrol(h)
        self.assertTrue(ok, engel)

        alim_uygunluk_uygula([h], {h.sembol}, 60)
        self.assertEqual(alim_aksiyon_hucre(h), "AL")
        self.assertIn("trend teyitli", h.alim_uygun_not)

    def test_dipten_donus_alim_firsati_gecer(self):
        h = _bist(
            sinyal="ALIM_FIRSATI",
            fiyat=170.0,
            sma200=175.0,
            zirve_52h_pct=55.0,
            degisim_1ay=-2.0,
            degisim_3ay=-4.0,
            endeks_gore=0.0,
        )
        ok, _ = _hikaye_al_kontrol(h)
        self.assertTrue(ok)

    def test_ekgyo_zayif_yil_bekle(self):
        h = _bist(
            sembol="EKGYO.IS",
            ad="Emlak Konut",
            sinyal="BEKLE",
            degisim_1y=7.0,
            degisim_1ay=9.0,
            degisim_3ay=8.9,
            bilesik_skor=90.0,
            skor=90.0,
        )
        alim_uygunluk_uygula([h], {h.sembol}, 60)
        self.assertEqual(alim_aksiyon_hucre(h), "BEKLE")
        self.assertIn("1 yıl", h.alim_uygun_not.lower())
        from alim_uygunluk import _tek_hisse_mi

        etf = _bist(piyasa="ETF", varlik_turu="etf", sinyal="BEKLE")
        self.assertFalse(_tek_hisse_mi(etf))
        ok, engel = _hikaye_al_kontrol(etf)
        self.assertTrue(ok)
        self.assertEqual(engel, [])


if __name__ == "__main__":
    unittest.main()
