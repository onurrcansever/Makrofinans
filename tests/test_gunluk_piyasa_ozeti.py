# -*- coding: utf-8 -*-
"""Günlük piyasa özeti — hazır soru yanıtı."""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from asistan_chat import (
    PIYASA_OZET_SORUSU,
    _piyasa_ozet_sorusu_mu,
    asistan_yanit,
    gunluk_piyasa_ozeti_metni,
)


@dataclass
class _FakeSnap:
    brent_usd: float = 92.0
    brent_1g_degisim: float = 0.5
    brent_3a_degisim: float = -10.0
    dxy: float = 104.0
    dxy_1g_degisim: float = 0.2
    abd_10y: float = 4.2
    abd_10y_1g_degisim: float = 0.1
    abd_30y: float = 4.5
    vix: float = 18.0
    vix_1g_degisim: float = -1.0
    bist100: float = 10500.0
    bist100_1g_degisim: float = 0.8
    bist_vol_30g: float = 22.0
    altin_usd_oz: float = 2300.0
    altin_1g_degisim: float = 0.3
    enflasyon_tr_yillik: float = 35.0
    eur_try_1g_degisim: float = 0.1
    veri: object = field(default_factory=lambda: type("V", (), {"eur_try": 36.5, "cds_5y_bp": 280})())


class GunlukPiyasaOzetiTest(unittest.TestCase):
    def test_soru_eslesme(self):
        self.assertTrue(_piyasa_ozet_sorusu_mu(PIYASA_OZET_SORUSU))
        self.assertTrue(_piyasa_ozet_sorusu_mu("bana bugün piyasaları yorumla"))
        self.assertFalse(_piyasa_ozet_sorusu_mu("AL adaylarım neler?"))

    def test_ozet_bolumler(self):
        from asistan_chat import _makro

        baglam = {
            "makro": _makro(_FakeSnap()),
            "rejim": "TL FIRSAT",
            "rejim_kod": "TL_FIRSAT",
            "endeksler": [{"ad": "BIST 100", "1g_pct": 0.5, "1a_pct": 2.0, "oneri": "Koru"}],
            "al_adaylari": [{
                "sembol": "THYAO.IS", "piyasa": "BIST", "skor": 72, "karar": "AL",
                "1g_pct": 1.2, "alim_seviyesi": 280.0,
            }],
            "al_adet": 1,
            "izle_takip": [{"sembol": "EQQQ.L", "piyasa": "ETF", "skor": 65}],
            "tefas_ust": [{"kod": "AFT", "ad": "Ak Portföy", "skor": 70, "oneri": "AL"}],
            "portfoy": {
                "pozisyon_adet": 1,
                "toplam_deger_tl": 100000,
                "agirlikli_getiri": {"1G": 0.5},
                "ust_pozisyonlar": [{
                    "sembol": "THYAO.IS", "deger": 50000, "getiri_1g": 1.0, "kz_pct": 5.0,
                }],
            },
            "tahsis_agirlik_pct": {"tl_deposit": 30, "gold": 15},
            "tarama_hareket": {
                "al_sayisi": {"BIST": 2, "ETF": 1},
                "izle_sayisi": {"NASDAQ": 3},
                "yukselenler": [{"sembol": "THYAO.IS", "1g_pct": 2.0}],
                "dusenler": [{"sembol": "X", "1g_pct": -1.5}],
            },
            "temkinli_rejim": False,
        }
        metin = gunluk_piyasa_ozeti_metni(baglam)
        for needle in (
            "Bugünün piyasa özeti",
            "CDS",
            "VIX",
            "BIST",
            "Brent",
            "DXY",
            "ABD 10Y",
            "Hisse & ETF",
            "THYAO.IS",
            "TEFAS",
            "Portföyünüz",
            "Bugün için 3 madde",
        ):
            self.assertIn(needle, metin)

    def test_asistan_deterministik_yanit(self):
        baglam = {
            "makro": {"vix": 18, "cds_5y_bp": 280, "bist100": 10000},
            "rejim": "Nötr",
            "rejim_kod": "NOTR",
            "al_adet": 0,
            "al_adaylari": [],
            "endeksler": [],
            "portfoy": {"pozisyon_adet": 0},
            "tarama_hareket": {},
            "temkinli_rejim": False,
        }
        # Anahtar yoksa motor iskeleti
        metin, meta = asistan_yanit(baglam, [], PIYASA_OZET_SORUSU)
        self.assertIn("Bugünün piyasa özeti", metin)
        self.assertIn("Kaynak:", metin)
        self.assertIn("Motordan özet", meta.get("hint") or "")

    def test_asistan_llm_mentor_mock(self):
        baglam = {
            "makro": {"vix": 18, "cds_5y_bp": 280, "bist100": 10000, "brent_usd": 90},
            "rejim": "Nötr",
            "rejim_kod": "NOTR",
            "al_adet": 0,
            "al_adaylari": [],
            "endeksler": [],
            "portfoy": {"pozisyon_adet": 0},
            "tarama_hareket": {},
            "temkinli_rejim": False,
        }

        def _mock(_prompt=None, **kwargs):
            return (
                "### Makro & rejim\n"
                "Bugün VIX sakin, CDS orta seviyede — rejim nötr okunuyor.\n\n"
                "### Bugün için 3 madde\n"
                "1. Para: tahsise sadık kal\n"
                "2. Hisse: AL yok, İZLE takip\n"
                "3. Bekle: CDS ve kur onayı"
            )

        metin, meta = asistan_yanit(
            baglam, [], PIYASA_OZET_SORUSU, _call_fn=_mock
        )
        self.assertIn("Makro", metin)
        self.assertEqual(meta.get("hint"), "Mentor yorumu (motordan rakamlar)")
        self.assertNotIn("Motor özeti — LLM yorumu değil", meta.get("hint") or "")


if __name__ == "__main__":
    unittest.main()
