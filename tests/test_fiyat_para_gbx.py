# -*- coding: utf-8 -*-
"""Integration: mispriced LSE rows must not render 50000+ USD."""
import unittest

from fiyat_para import kaynak_para_birimi, tablo_fiyat
from signal_engine.data.quote_normalize import MissingQuoteCurrencyError


class FiyatParaGbxIntegrationTest(unittest.TestCase):
    def test_eqqq_l_normalized_price_display(self):
        from signal_engine.data.quote_normalize import normalize_price
        raw_pence = 47000.0
        q = normalize_price(raw_pence, "GBp")
        pb = kaynak_para_birimi("EQQQ.L", piyasa="ETF", varlik_turu="etf")
        self.assertEqual(pb, "GBP")
        displayed = tablo_fiyat(
            q.amount, "USD", eur_try=35.0, usd_try=38.0,
            sembol="EQQQ.L", piyasa="ETF", varlik_turu="etf",
            kaynak_pb=pb, quote_currency="GBP",
            gbp_usd=1.34, eur_usd=38.0 / 35.0,
        )
        self.assertIsNotNone(displayed)
        self.assertLess(displayed, 1000, f"EQQQ USD display must be ~hundreds, got {displayed}")
        self.assertGreater(displayed, 300)

    def test_raw_pence_display_coerced(self):
        """Ham pence (68670) + quote_currency=GBp → ~687 USD, 68670 değil."""
        displayed = tablo_fiyat(
            68670.0, "USD", eur_try=35.0, usd_try=38.0,
            sembol="EQQQ.L", piyasa="ETF", varlik_turu="etf",
            quote_currency="GBp",
            gbp_usd=1.34, eur_usd=38.0 / 35.0,
        )
        self.assertIsNotNone(displayed)
        self.assertLess(displayed, 1000, f"ham pence coerced, got {displayed}")
        self.assertGreater(displayed, 400)

    def test_raw_pence_without_quote_currency_raises(self):
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(
                68670.0, "USD", eur_try=35.0, usd_try=38.0,
                sembol="EQQQ.L", piyasa="ETF", varlik_turu="etf",
                gbp_usd=1.34, eur_usd=38.0 / 35.0,
            )

    def test_raw_emim_pence(self):
        displayed = tablo_fiyat(
            5091.0, "USD", eur_try=35.0, usd_try=38.0,
            sembol="EMIM.L", piyasa="ETF", varlik_turu="etf",
            quote_currency="GBp",
            gbp_usd=1.34, eur_usd=38.0 / 35.0,
        )
        self.assertLess(displayed, 100)
        self.assertGreater(displayed, 30)

    def test_vusa_settled_gbp_not_redivided(self):
        displayed = tablo_fiyat(
            79.0, "EUR", eur_try=38.0, usd_try=41.0,
            sembol="VUSA.L", piyasa="ETF", varlik_turu="etf",
            quote_currency="GBP",
            gbp_usd=1.34, eur_usd=41.0 / 38.0,
        )
        self.assertGreater(displayed, 80)
        self.assertGreater(displayed / 1.1868, 50)

    def test_vusa_without_quote_currency_raises(self):
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(
                79.0, "EUR", eur_try=38.0, usd_try=41.0,
                sembol="VUSA.L", piyasa="ETF", varlik_turu="etf",
                gbp_usd=1.34, eur_usd=41.0 / 38.0,
            )

    def test_emim_normalized_gbp_display(self):
        from signal_engine.data.quote_normalize import normalize_price
        q = normalize_price(4009.0, "GBp")
        displayed = tablo_fiyat(
            q.amount, "USD", eur_try=35.0, usd_try=38.0,
            sembol="EMIM.L", piyasa="ETF", varlik_turu="etf",
            gbp_usd=1.34, eur_usd=38.0 / 35.0,
            kaynak_pb="GBP", quote_currency="GBP",
        )
        self.assertGreater(displayed, 25)
        self.assertLess(displayed, 80)


if __name__ == "__main__":
    unittest.main()
