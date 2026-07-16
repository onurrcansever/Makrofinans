# -*- coding: utf-8 -*-
"""Canlı kotasyon ve veri tazeliği testleri."""
import unittest
from datetime import datetime, timezone

import pandas as pd

from signal_engine.data.live_quote import quote_age_from_bar


class LiveQuoteAgeTest(unittest.TestCase):
    def test_midnight_bar_session_open_not_19h(self):
        """Aynı gün seans içindeyken gece yarısı barı ~19 saat göstermemeli."""
        bar = pd.Timestamp("2026-07-14 00:00:00", tz="UTC")
        age = quote_age_from_bar(bar, "SP500")
        self.assertIsNotNone(age)
        # Canlı test ortamında seans dışı olabilir; 19 saat (1140 dk) eşiğinin altında olmalı
        self.assertLess(age, 1140, f"midnight bar inflated to ~19h, got {age:.0f} min")

    def test_midnight_bar_bist(self):
        bar = pd.Timestamp("2026-07-14 00:00:00", tz="UTC")
        age = quote_age_from_bar(bar, "BIST")
        self.assertIsNotNone(age)
        self.assertLess(age, 1140)


if __name__ == "__main__":
    unittest.main()
