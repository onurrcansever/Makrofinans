# -*- coding: utf-8 -*-
"""EndeksAI LLM — mock API + cache."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

import llm_endeks as le
from signal_engine.explain.endeks_snapshot import build_endeks_snapshot


class LlmEndeksTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = le.STATE_PATH
        le.STATE_PATH = os.path.join(self._td.name, "endeks_cache.json")
        le.clear_rate_limit_for_tests()

    def tearDown(self):
        le.STATE_PATH = self._orig
        self._td.cleanup()
        le.clear_rate_limit_for_tests()

    def _snap(self):
        e = SimpleNamespace(
            ad="BIST 100",
            sembol="XU100.IS",
            aksiyon_etiket="Azalt",
            guven=71,
            kurulum="Zayıf momentum",
            platform="TR",
            degisim_1ay=-5.0,
            degisim_3ay=-3.0,
            teknik_aksiyon_etiket="Azalt",
            makro_chip="",
            gerekce="Ağırlığı azalt",
        )
        return build_endeks_snapshot(
            [e],
            oncelik="Bugün bakılacak yer: **ABD**",
            gosterim_pb="EUR",
            makro_rejim="NOTR",
            gosterim_getiriler={"XU100.IS": {"1a": -6.2, "3a": -4.0}},
        )

    def test_prompt_has_lejant_and_flow(self):
        seen = {"p": ""}

        def mock_call(prompt, **kw):
            seen["p"] = prompt
            return (
                "Bugün bakılacak yer ABD tarafı. BIST Azalt platform ağırlığını "
                "düşürmek demek; hisse AL’yi veto etmez, seçici olun. "
                "EUR sütun gösterimdir. Makro sonra endeks sonra hisse okuyun."
            )

        metin, meta = le.endeks_aciklamasi(
            self._snap(), gosterim_pb="EUR", _call_fn=mock_call,
        )
        p = seen["p"]
        self.assertIn("pozisyon ağırlığı", p)
        self.assertIn("hisse", p.lower())
        self.assertIn("EUR", p)
        self.assertIn("8–12 cümle", p)
        self.assertIn("İZLE", p)
        self.assertNotIn("MACD", metin)
        self.assertFalse(meta["cache_hit"])

        metin2, meta2 = le.endeks_aciklamasi(
            self._snap(), gosterim_pb="EUR", _call_fn=mock_call,
        )
        self.assertTrue(meta2["cache_hit"])
        self.assertEqual(metin, metin2)

    def test_format_markdown(self):
        md = le.format_endeks_ai_markdown(
            "Örnek endeks notu.",
            {"guncelleme": "2026-07-22", "hint": "EndeksAI"},
        )
        self.assertIn("EndeksAI", md)
        self.assertIn("22 Tem 2026", md)


if __name__ == "__main__":
    unittest.main()
