# -*- coding: utf-8 -*-
"""Premarket — LiveQuote alanları + tablo hücre formatı (skor yoluna dokunmaz)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from signal_engine.data.live_quote import (
    LiveQuote,
    _fetch_one,
    _quote_from_dict,
    _quote_to_dict,
    format_premarket_cell,
)


class FormatPremarketCellTest(unittest.TestCase):
    def test_non_us_dash(self):
        self.assertEqual(format_premarket_cell("BIST", 185.0, 180.0), "—")
        self.assertEqual(format_premarket_cell("ETF", 10.0), "—")
        self.assertEqual(format_premarket_cell("EMTIA", 2000.0), "—")

    def test_us_none_dash(self):
        self.assertEqual(format_premarket_cell("SP500", None), "—")
        self.assertEqual(format_premarket_cell("NASDAQ", None, 100.0), "—")

    def test_yahoo_change_pct_preferred(self):
        # AMAT tarzı: previousClose yanlış baz verirse change_pct kazanır
        s = format_premarket_cell(
            "SP500",
            543.0,
            525.7,
            display_price=543.0,
            change_pct=-3.8171976,
        )
        self.assertEqual(s, "543.00 (-3.8%)")

    def test_ref_price_over_previous_close(self):
        # Revolut/Yahoo baz = son regular (564.55), previousClose=525.7 yanıltıcı
        s = format_premarket_cell(
            "NASDAQ",
            543.0,
            525.7,
            display_price=543.0,
            ref_price_native=564.55,
        )
        self.assertEqual(s, "543.00 (-3.8%)")

    def test_us_price_display_fx(self):
        s = format_premarket_cell(
            "NASDAQ", 100.0, display_price=92.5, change_pct=0.0,
        )
        self.assertEqual(s, "92.50 (+0.0%)")

    def test_us_price_no_pct_inputs(self):
        self.assertEqual(
            format_premarket_cell("SP500", 50.0, None, display_price=50.0),
            "50.00",
        )


class LiveQuotePremarketFetchTest(unittest.TestCase):
    def test_fetch_sets_premarket_keeps_regular_price(self):
        fi = {
            "lastPrice": 564.55,
            "currency": "USD",
            "regularMarketTime": datetime.now(timezone.utc).timestamp(),
            "marketState": "PRE",
        }
        info = {
            "preMarketPrice": 543.0,
            "preMarketChangePercent": -3.8171976,
            "marketState": "PRE",
            "currency": "USD",
            "regularMarketPrice": 564.55,
            "regularMarketPreviousClose": 525.7,
        }
        ticker = MagicMock()
        ticker.fast_info = fi
        ticker.info = info
        ticker.history.return_value = MagicMock(empty=True)

        with patch("yfinance.Ticker", return_value=ticker):
            q = _fetch_one("AMAT")

        self.assertIsNotNone(q)
        assert q is not None
        self.assertAlmostEqual(q.price, 564.55)
        self.assertAlmostEqual(q.premarket_price or 0, 543.0)
        self.assertEqual(q.market_state, "PRE")
        self.assertAlmostEqual(q.premarket_change_pct or 0, -3.8171976, places=4)

    def test_cache_roundtrip_premarket(self):
        q = LiveQuote(
            price=564.55,
            currency="USD",
            settlement="USD",
            timestamp=datetime.now(timezone.utc),
            age_min=1.0,
            previous_close=525.7,
            cached_at=1_700_000_000.0,
            premarket_price=543.0,
            market_state="PRE",
            premarket_change_pct=-3.82,
        )
        d = _quote_to_dict(q)
        self.assertEqual(d["premarket_price"], 543.0)
        self.assertEqual(d["market_state"], "PRE")
        self.assertAlmostEqual(d["premarket_change_pct"], -3.82)
        back = _quote_from_dict(d)
        self.assertIsNotNone(back)
        assert back is not None
        self.assertAlmostEqual(back.premarket_price or 0, 543.0)
        self.assertEqual(back.market_state, "PRE")
        self.assertAlmostEqual(back.premarket_change_pct or 0, -3.82)
        self.assertAlmostEqual(back.price, 564.55)

    def test_old_cache_without_premarket(self):
        d = {
            "price": 50.0,
            "currency": "USD",
            "settlement": "USD",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_close": 49.0,
            "cached_at": 1_700_000_000.0,
        }
        back = _quote_from_dict(d)
        self.assertIsNotNone(back)
        assert back is not None
        self.assertIsNone(back.premarket_price)
        self.assertIsNone(back.premarket_change_pct)
        self.assertEqual(back.market_state, "")


if __name__ == "__main__":
    unittest.main()
