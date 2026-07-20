# -*- coding: utf-8 -*-
"""Groq kota snapshot + caption."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import llm_client as lc


class GroqKotaTest(unittest.TestCase):
    def setUp(self):
        self._td = __import__("tempfile").TemporaryDirectory()
        lc.QUOTA_PATH = __import__("os").path.join(self._td.name, "q.json")
        lc._last_quota = {}

    def tearDown(self):
        self._td.cleanup()

    def test_429_body_tpd(self):
        body = (
            'Rate limit reached for model `llama-3.3-70b-versatile` '
            "on tokens per day (TPD): Limit 100000, Used 97066, Requested 2000"
        )
        lc._update_quota_from_429_body(body)
        q = lc.groq_kota_ozeti()
        self.assertEqual(q.get("tpd_limit"), 100000)
        self.assertEqual(q.get("tpd_kalan"), 100000 - 97066)
        with patch.object(lc, "resolve_provider", return_value="groq"):
            with patch.object(lc, "resolve_model", return_value="llama-3.3-70b-versatile"):
                cap = lc.provider_kota_caption()
        self.assertIn("token/gün", cap)

    def test_headers_rpd_tpm(self):
        class H(dict):
            def get(self, k, default=None):
                return dict.get(self, k, default)

        headers = H({
            "x-ratelimit-remaining-requests": "100",
            "x-ratelimit-limit-requests": "14400",
            "x-ratelimit-remaining-tokens": "5000",
            "x-ratelimit-limit-tokens": "6000",
        })
        lc._update_quota_from_headers(
            headers,
            model="llama-3.1-8b-instant",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        q = lc.groq_kota_ozeti()
        self.assertEqual(q.get("rpd_kalan"), 100)
        self.assertEqual(q.get("tpm_kalan"), 5000)
        self.assertEqual(q.get("tpd_kullanilan_tahmini"), 150)
        with patch.object(lc, "resolve_provider", return_value="groq"):
            with patch.object(lc, "resolve_model", return_value="llama-3.1-8b-instant"):
                cap = lc.provider_kota_caption()
        self.assertIn("istek/gün", cap)
        self.assertIn("tpm", cap)


if __name__ == "__main__":
    unittest.main()
