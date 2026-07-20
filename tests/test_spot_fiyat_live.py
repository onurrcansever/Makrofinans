# -*- coding: utf-8 -*-
"""spot_fiyat_veya_live — tarama boşken canlı kotasyon yedeği."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fiyat_para import spot_fiyat_veya_live
from signal_engine.data.live_quote import LiveQuote


class SpotFiyatVeyaLiveTest(unittest.TestCase):
    def test_tarama_fiyati_oncelikli(self):
        px, qc = spot_fiyat_veya_live("GC=F", 4000.0, "USD")
        self.assertEqual(px, 4000.0)
        self.assertEqual(qc, "USD")

    def test_live_fallback(self):
        live = LiveQuote(
            price=4012.8,
            currency="USD",
            settlement="USD",
            timestamp=datetime.now(timezone.utc),
            age_min=1.0,
        )
        with patch("signal_engine.data.live_quote.get_live_quote", return_value=live):
            px, qc = spot_fiyat_veya_live("GC=F", None, "")
        self.assertAlmostEqual(px, 4012.8)
        self.assertEqual(qc, "USD")

    def test_bos(self):
        with patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            px, qc = spot_fiyat_veya_live("XYZ", None, "EUR")
        self.assertIsNone(px)
        self.assertEqual(qc, "EUR")


if __name__ == "__main__":
    unittest.main()
