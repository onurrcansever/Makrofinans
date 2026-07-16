# -*- coding: utf-8 -*-
"""Aşama 2C — portföy genel yorumu testleri (mock LLM)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import portfoy_yorum as py


class PortfoyYorumTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = py.STATE_PATH
        py.STATE_PATH = os.path.join(self._td.name, "py_cache.json")
        py.clear_rate_limit_for_tests()

    def tearDown(self):
        py.STATE_PATH = self._orig
        self._td.cleanup()
        py.clear_rate_limit_for_tests()

    def test_konsantrasyon_sektor_agirliklari(self):
        satirlar = [
            {"sembol": "MSFT", "tur": "hisse", "deger": 380},
            {"sembol": "AAPL", "tur": "hisse", "deger": 200},
            {"sembol": "NVDA", "tur": "hisse", "deger": 220},
            {"sembol": "GARAN.IS", "tur": "hisse", "deger": 100},
            {"sembol": "EQQQ.L", "tur": "etf", "deger": 100},
        ]
        pct, en_buyuk, uyari = py.sektor_agirliklari(satirlar)
        self.assertAlmostEqual(pct["ABD teknoloji"], 80.0, delta=0.5)
        self.assertIn("ABD teknoloji", en_buyuk or "")
        self.assertTrue(uyari)

        ozet = py.portfoy_ozet_hesapla(
            [
                {"sembol": "MSFT", "tur": "hisse", "miktar": 1, "maliyet": 300,
                 "kar_zarar_pct": 10, "deger": 380},
                {"sembol": "AAPL", "tur": "hisse", "miktar": 1, "maliyet": 180,
                 "kar_zarar_pct": 5, "deger": 200},
                {"sembol": "NVDA", "tur": "hisse", "miktar": 1, "maliyet": 100,
                 "kar_zarar_pct": 50, "deger": 220},
                {"sembol": "GARAN.IS", "tur": "hisse", "miktar": 10, "maliyet": 90,
                 "kar_zarar_pct": 5, "deger": 100},
                {"sembol": "EQQQ.L", "tur": "etf", "miktar": 2, "maliyet": 90,
                 "kar_zarar_pct": 8, "deger": 100},
            ]
        )
        self.assertTrue(ozet["konsantrasyon_uyari"])
        self.assertIn("ABD teknoloji", ozet["en_buyuk_sektor"])

    def test_sinyal_uyumu_azalt_agirlik(self):
        # Eşit değer: 3/6 = %50 AZALT
        poz = [
            {"sembol": "INTU", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": -62, "deger": 100},
            {"sembol": "ORCL", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": -41, "deger": 100},
            {"sembol": "NFLX", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": -41, "deger": 100},
            {"sembol": "MSFT", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": 10, "deger": 100},
            {"sembol": "AAPL", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": 5, "deger": 100},
            {"sembol": "CSCO", "tur": "hisse", "miktar": 1, "maliyet": 100,
             "kar_zarar_pct": 68, "deger": 100},
        ]
        tarama = [
            SimpleNamespace(sembol="INTU", signal_v2_decision="AZALT", signal_v2_score=35),
            SimpleNamespace(sembol="ORCL", signal_v2_decision="AZALT", signal_v2_score=38),
            SimpleNamespace(sembol="NFLX", signal_v2_decision="AZALT", signal_v2_score=40),
            SimpleNamespace(sembol="MSFT", signal_v2_decision="İZLE", signal_v2_score=55),
            SimpleNamespace(sembol="AAPL", signal_v2_decision="AL", signal_v2_score=70),
            SimpleNamespace(sembol="CSCO", signal_v2_decision="BEKLE", signal_v2_score=48),
        ]
        ozet = py.portfoy_ozet_hesapla(poz, tarama)
        self.assertEqual(ozet["toplam_pozisyon"], 6)
        self.assertAlmostEqual(ozet["azalt_agirlik_pct"], 50.0, delta=0.2)
        self.assertEqual(ozet["karar_sayilari"].get("AZALT"), 3)
        self.assertEqual(ozet["ortalama_skor"], 48)  # (35+38+40+55+70+48)/6

    def test_llm_timeout_fallback(self):
        def slow(prompt, **kw):
            time.sleep(2.0)
            return "geç"

        ozet = {
            "toplam_pozisyon": 3,
            "azalt_agirlik_pct": 10.0,
            "ortalama_skor": 50,
            "en_buyuk_sektor": "ABD teknoloji %40",
            "konsantrasyon_uyari": True,
            "portfoy_kz_pct": -5.0,
            "en_zararli": ["INTU -62%"],
            "en_kazanli": ["CSCO +68%"],
        }
        metin, meta = py.portfoy_genel_yorum(ozet, timeout=0.15, _call_fn=slow)
        self.assertEqual(metin, py.FALLBACK)
        self.assertEqual(meta.get("hata"), "timeout")

    def test_cache_6h_no_refetch(self):
        calls = {"n": 0}

        def mock_call(prompt, **kw):
            calls["n"] += 1
            return "Portföy dengeli görünüyor."

        ozet = {
            "toplam_pozisyon": 4,
            "azalt_agirlik_pct": 25.3,
            "ortalama_skor": 54,
            "en_buyuk_sektor": "ABD teknoloji %38",
            "konsantrasyon_uyari": True,
            "portfoy_kz_pct": -8.2,
            "en_zararli": ["INTU -62%", "ORCL -41%", "NFLX -41%"],
            "en_kazanli": ["AMAT +196%", "MU +663%", "CSCO +68%"],
        }
        poz = [{"sembol": f"S{i}", "miktar": 1, "maliyet": 10, "kar_zarar_pct": i}
               for i in range(4)]
        m1, meta1 = py.portfoy_genel_yorum(
            ozet, pozisyon_listesi=poz, _call_fn=mock_call,
        )
        self.assertFalse(meta1["cache_hit"])
        m2, meta2 = py.portfoy_genel_yorum(
            ozet, pozisyon_listesi=poz, _call_fn=mock_call,
        )
        self.assertTrue(meta2["cache_hit"])
        self.assertEqual(calls["n"], 1)
        self.assertEqual(m1, m2)

    def test_cache_stale_after_6h(self):
        ozet = {
            "toplam_pozisyon": 2,
            "azalt_agirlik_pct": 0,
            "ortalama_skor": 60,
            "en_buyuk_sektor": "ETF %100",
            "konsantrasyon_uyari": True,
            "portfoy_kz_pct": 1.0,
            "en_zararli": ["EQQQ +1%"],
            "en_kazanli": ["CSPX +2%"],
        }
        poz = [{"sembol": "EQQQ", "miktar": 1, "maliyet": 1, "kar_zarar_pct": 1}]
        calls = {"n": 0}

        def mock_call(prompt, **kw):
            calls["n"] += 1
            return f"yorum-{calls['n']}"

        py.portfoy_genel_yorum(ozet, pozisyon_listesi=poz, _call_fn=mock_call)
        # Cache kaydını 7 saat geriye al
        cache = py.yukle_cache()
        for ent in cache.values():
            ent["guncelleme"] = (
                datetime.now(timezone.utc) - timedelta(hours=7)
            ).isoformat()
        py.kaydet_cache(cache)
        py.portfoy_genel_yorum(ozet, pozisyon_listesi=poz, _call_fn=mock_call)
        self.assertEqual(calls["n"], 2)

    def test_gizlilik_promptta_sembol_yok(self):
        ozet = {
            "toplam_pozisyon": 12,
            "azalt_agirlik_pct": 25.3,
            "ortalama_skor": 54,
            "en_buyuk_sektor": "ABD teknoloji %38",
            "konsantrasyon_uyari": True,
            "portfoy_kz_pct": -8.2,
            "en_zararli": ["INTU -62%", "ORCL -41%", "NFLX -41%"],
            "en_kazanli": ["AMAT +196%", "MU +663%", "CSCO +68%"],
        }
        prompt = py._build_prompt(ozet)
        self.assertFalse(py.prompt_sembol_icerir_mi(prompt))
        for sym in ("INTU", "ORCL", "NFLX", "AMAT", "MU", "CSCO", "MSFT"):
            self.assertNotIn(sym, prompt)
        self.assertNotIn("miktar", prompt.lower())
        self.assertNotIn("maliyet", prompt.lower())
        # Yüzdeler kalmalı
        self.assertIn("-62%", prompt)
        self.assertIn("+196%", prompt)

        seen = {"p": ""}

        def mock_call(prompt, **kw):
            seen["p"] = prompt
            return "Özet yorum."

        py.portfoy_genel_yorum(ozet, _call_fn=mock_call, force=True)
        self.assertFalse(py.prompt_sembol_icerir_mi(seen["p"]))

    def test_ornek_ozet_dict_yapisi(self):
        poz = [
            {"sembol": "INTU", "deger": 50, "maliyet": 130, "kar_zarar_pct": -62, "tur": "hisse"},
            {"sembol": "ORCL", "deger": 50, "maliyet": 85, "kar_zarar_pct": -41, "tur": "hisse"},
            {"sembol": "NFLX", "deger": 50, "maliyet": 85, "kar_zarar_pct": -41, "tur": "hisse"},
            {"sembol": "AMAT", "deger": 80, "maliyet": 27, "kar_zarar_pct": 196, "tur": "hisse"},
            {"sembol": "MU", "deger": 80, "maliyet": 10, "kar_zarar_pct": 663, "tur": "hisse"},
            {"sembol": "CSCO", "deger": 60, "maliyet": 36, "kar_zarar_pct": 68, "tur": "hisse"},
            {"sembol": "MSFT", "deger": 100, "maliyet": 90, "kar_zarar_pct": 10, "tur": "hisse"},
            {"sembol": "AAPL", "deger": 90, "maliyet": 80, "kar_zarar_pct": 12, "tur": "hisse"},
            {"sembol": "NVDA", "deger": 90, "maliyet": 70, "kar_zarar_pct": 20, "tur": "hisse"},
            {"sembol": "META", "deger": 70, "maliyet": 60, "kar_zarar_pct": 15, "tur": "hisse"},
            {"sembol": "GARAN.IS", "deger": 40, "maliyet": 35, "kar_zarar_pct": 14, "tur": "hisse"},
            {"sembol": "EQQQ.L", "deger": 40, "maliyet": 35, "kar_zarar_pct": 8, "tur": "etf"},
        ]
        ozet = py.portfoy_ozet_hesapla(poz)
        for k in (
            "toplam_pozisyon", "azalt_agirlik_pct", "ortalama_skor",
            "en_buyuk_sektor", "konsantrasyon_uyari", "portfoy_kz_pct",
            "en_zararli", "en_kazanli",
        ):
            self.assertIn(k, ozet)
        self.assertEqual(ozet["toplam_pozisyon"], 12)
        self.assertTrue(any("INTU" in x for x in ozet["en_zararli"]))


if __name__ == "__main__":
    unittest.main()
