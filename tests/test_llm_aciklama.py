# -*- coding: utf-8 -*-
"""LLM açıklama — mock API, cache, timeout, çelişki, ETF."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import llm_aciklama as llm


class LlmAciklamaTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = llm.STATE_PATH
        llm.STATE_PATH = os.path.join(self._td.name, "llm_cache.json")
        llm.clear_rate_limit_for_tests()

    def tearDown(self):
        llm.STATE_PATH = self._orig
        self._td.cleanup()
        llm.clear_rate_limit_for_tests()

    def test_cache_ttl_hit(self):
        calls = {"n": 0}

        def mock_call(prompt, **kw):
            calls["n"] += 1
            return "İlk açıklama metni."

        m1, meta1 = llm.hisse_aciklamasi(
            "MSFT", "AZALT", 40, {}, {}, 400.0, 10.0, "NOTR",
            _call_fn=mock_call,
        )
        self.assertFalse(meta1["cache_hit"])
        self.assertEqual(calls["n"], 1)

        m2, meta2 = llm.hisse_aciklamasi(
            "MSFT", "AZALT", 40, {}, {}, 400.0, 10.0, "NOTR",
            _call_fn=mock_call,
        )
        self.assertTrue(meta2["cache_hit"])
        self.assertEqual(calls["n"], 1)
        self.assertEqual(m1, m2)

    def test_cache_miss_on_skor_change(self):
        calls = {"n": 0}

        def mock_call(prompt, **kw):
            calls["n"] += 1
            return f"call-{calls['n']}"

        llm.hisse_aciklamasi(
            "MSFT", "AZALT", 40, {}, {}, 400.0, 10.0, "NOTR", _call_fn=mock_call,
        )
        llm.hisse_aciklamasi(
            "MSFT", "AZALT", 45, {}, {}, 400.0, 10.0, "NOTR", _call_fn=mock_call,
        )
        self.assertEqual(calls["n"], 2)

    def test_timeout_fallback(self):
        def slow(prompt, **kw):
            time.sleep(2.0)
            return "geç"

        metin, meta = llm.hisse_aciklamasi(
            "MSFT", "İZLE", 50, {}, {}, 100.0, 0.0, "NOTR",
            timeout=0.15, _call_fn=slow,
        )
        self.assertEqual(metin, llm.FALLBACK)
        self.assertEqual(meta.get("hata"), "timeout")

    def test_celiski_azalt_strong_buy(self):
        def mock_call(prompt, **kw):
            self.assertIn("AZALT", prompt)
            self.assertIn("strong_buy", prompt)
            return (
                "Teknik olarak AZALT sinyali var ancak analist konsensüsü güçlü al — "
                "bu çelişki teyit gerektirir."
            )

        metin, _ = llm.hisse_aciklamasi(
            "MSFT",
            "AZALT",
            40,
            {"trend": 30, "mean_reversion": 40, "volatility": 50,
             "relative_strength": 35, "liquidity": 70},
            {
                "tur": "hisse",
                "analist": "strong_buy",
                "analist_sayi": 55,
                "hedef_fark_pct": 40.0,
                "fk_trailing": 24.0,
            },
            400.0,
            12.0,
            "NOTR",
            _call_fn=mock_call,
        )
        self.assertIn("çelişki", metin.lower())

    def test_etf_format_in_prompt(self):
        seen = {"p": ""}

        def mock_call(prompt, **kw):
            seen["p"] = prompt
            return "ETF teknik notu."

        llm.hisse_aciklamasi(
            "EQQQ.L", "İZLE", 64, {},
            {"tur": "etf", "not": "ETF için analist konsensüsü yok"},
            625.0, 20.0, "NOTR",
            _call_fn=mock_call,
        )
        self.assertIn("ETF — temel analiz verisi yok", seen["p"])

    def test_format_ai_markdown(self):
        md = llm.format_ai_markdown(
            "Örnek not.",
            {"guncelleme": "2026-07-16"},
        )
        self.assertIn("AI Analiz", md)
        self.assertIn("·", md)
        self.assertTrue("AI" in md or "Groq" in md or "Claude" in md or "llama" in md.lower())
        self.assertIn("16 Tem 2026", md)

    def test_stale_cache_refetch(self):
        key = llm.cache_anahtar("AAPL", "AL", 70)
        llm.kaydet_cache({
            key: {
                "metin": "eski",
                "guncelleme": (date.today() - timedelta(days=2)).isoformat(),
            },
        })
        calls = {"n": 0}

        def mock_call(prompt, **kw):
            calls["n"] += 1
            return "yeni"

        metin, meta = llm.hisse_aciklamasi(
            "AAPL", "AL", 70, {}, {}, 150.0, 5.0, "NOTR", _call_fn=mock_call,
        )
        self.assertEqual(calls["n"], 1)
        self.assertFalse(meta["cache_hit"])
        self.assertEqual(metin, "yeni")


if __name__ == "__main__":
    unittest.main()
