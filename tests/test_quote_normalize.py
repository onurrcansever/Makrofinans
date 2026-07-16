# -*- coding: utf-8 -*-
"""BUG 1 — GBX/pence normalization regression tests."""
import unittest

import numpy as np
import pandas as pd

from fiyat_para import tablo_fiyat
from signal_engine.data.quote_normalize import (
    MissingQuoteCurrencyError,
    coerce_settlement_amount,
    normalize_close_series,
    normalize_price,
    resolve_quote_currency,
    sanity_check_lse_magnitude,
    sanity_check_vs_median,
    to_display_currency,
)

VUSA_GBP = 79.0  # ~93 EUR doğru bant
VHYL_GBP = 60.0


class QuoteNormalizeTest(unittest.TestCase):
    def test_resolve_eqqq_is_gbp_pence_not_usd(self):
        self.assertEqual(resolve_quote_currency("EQQQ.L"), "GBp")
        self.assertEqual(resolve_quote_currency("CSPX.L"), "USD")

    def test_yahoo_gbp_not_mapped_to_pence(self):
        self.assertEqual(resolve_quote_currency("VUSA.L", "GBP"), "GBP")
        self.assertEqual(resolve_quote_currency("VUSA.L", "GBp"), "GBp")

    def test_gbx_to_gbp_divide_by_100(self):
        q = normalize_price(47000.0, "GBp")
        self.assertAlmostEqual(q.amount, 470.0)
        self.assertEqual(q.currency, "GBP")

    def test_gbp_amount_idempotent(self):
        q = normalize_price(93.41, "GBP")
        self.assertAlmostEqual(q.amount, 93.41)
        self.assertEqual(q.currency, "GBP")
        self.assertTrue(q.already_settled)

    def test_gbx_guess_threshold_skips_small_amounts(self):
        """allow_guess yolunda küçük değerler /100 yapılmaz (suffix tahmini)."""
        q = normalize_price(93.41, "GBp", guess=True)
        self.assertAlmostEqual(q.amount, 93.41)

    def test_settled_gbp_never_redivided(self):
        q = coerce_settlement_amount("VUSA.L", VUSA_GBP, "GBP")
        self.assertAlmostEqual(q.amount, VUSA_GBP)
        self.assertEqual(q.currency, "GBP")
        self.assertTrue(q.already_settled)

    def test_coerce_missing_quote_currency_raises(self):
        with self.assertRaises(MissingQuoteCurrencyError):
            coerce_settlement_amount("EQQQ.L", 533.44, "")

    def test_coerce_idempotent_gbp(self):
        q1 = coerce_settlement_amount("EQQQ.L", 533.44, "GBP")
        q2 = coerce_settlement_amount("EQQQ.L", q1.amount, "GBP")
        self.assertAlmostEqual(q1.amount, q2.amount)
        self.assertTrue(q2.already_settled)

    def test_normalize_idempotent_gbp(self):
        q1 = normalize_price(533.44, "GBP")
        q2 = normalize_price(q1.amount, q1.currency)
        self.assertAlmostEqual(q1.amount, q2.amount)
        self.assertTrue(q1.already_settled)
        self.assertTrue(q2.already_settled)

    def test_normalize_idempotent_gbx_pence(self):
        q1 = normalize_price(47000.0, "GBp")
        q2 = normalize_price(q1.amount, "GBP")
        self.assertAlmostEqual(q1.amount, q2.amount)
        self.assertAlmostEqual(q1.amount, 470.0)

    def test_eqqq_style_usd_display_range(self):
        q = normalize_price(47000.0, "GBp")
        usd = to_display_currency(q.amount, q.currency, "USD", eur_try=38.0, usd_try=41.0, gbp_usd=1.34, eur_usd=1.08)
        self.assertGreater(usd, 300)
        self.assertLess(usd, 650)

    def test_emim_style_usd_display_range(self):
        q = normalize_price(4009.0, "GBp")
        usd = to_display_currency(q.amount, q.currency, "USD", eur_try=38.0, usd_try=41.0, gbp_usd=1.34, eur_usd=1.08)
        self.assertGreater(usd, 25)
        self.assertLess(usd, 80)

    def test_cspx_usd_unchanged(self):
        q = normalize_price(520.5, "USD")
        self.assertAlmostEqual(q.amount, 520.5)
        self.assertEqual(q.currency, "USD")

    def test_eqqq_series_not_quarantined_when_consistent(self):
        pence = pd.Series(np.linspace(46000, 48000, 220))
        norm, meta = normalize_close_series("EQQQ.L", pence)
        self.assertFalse(meta.quarantine, meta.quarantine_reason)
        self.assertAlmostEqual(norm.iloc[-1], 480.0, places=0)

    def test_vusa_already_gbp_series_not_divided(self):
        s = pd.Series([VUSA_GBP - 2 + i * 0.01 for i in range(220)])
        norm, meta = normalize_close_series("VUSA.L", s, source_currency="GBP")
        self.assertAlmostEqual(norm.iloc[-1], VUSA_GBP - 0.01, delta=0.5)
        self.assertFalse(meta.quarantine, meta.quarantine_reason)

    def test_vusa_pence_series_divided_once(self):
        s = pd.Series([7900.0 + i for i in range(220)])
        norm, meta = normalize_close_series("VUSA.L", s, source_currency="GBp")
        self.assertAlmostEqual(norm.iloc[-1], 79.0 + 219 / 100.0, delta=0.5)
        self.assertFalse(meta.quarantine, meta.quarantine_reason)

    def test_vusa_double_converted_series_quarantined(self):
        s = pd.Series([0.934] * 220)
        norm, meta = normalize_close_series("VUSA.L", s, source_currency="GBP")
        self.assertTrue(meta.quarantine, meta.quarantine_reason)
        self.assertIn("çifte GBX", meta.quarantine_reason)

    def test_vusa_display_eur_not_double_converted(self):
        eur = tablo_fiyat(
            VUSA_GBP, "EUR", eur_try=38.0, usd_try=41.0,
            sembol="VUSA.L", quote_currency="GBP",
            gbp_usd=1.34, eur_usd=41.0 / 38.0,
        )
        self.assertIsNotNone(eur)
        self.assertGreater(eur, 80, f"VUSA EUR must be ~93 band, got {eur}")
        self.assertGreater(eur / 1.1868, 50, "must not be ~78× too low")

    def test_vusa_display_without_quote_currency_raises(self):
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(
                VUSA_GBP, "EUR", eur_try=38.0, usd_try=41.0,
                sembol="VUSA.L",
                gbp_usd=1.34, eur_usd=41.0 / 38.0,
            )

    def test_vhyL_display_eur(self):
        eur = tablo_fiyat(
            VHYL_GBP, "EUR", eur_try=38.0, usd_try=41.0,
            sembol="VHYL.L", quote_currency="GBP",
            gbp_usd=1.34, eur_usd=41.0 / 38.0,
        )
        self.assertGreater(eur, 45)
        self.assertLess(eur, 90)

    def test_sanity_quarantine_on_absurd_spike(self):
        s = pd.Series([100.0] * 200 + [600.0])
        ok, reason, _ = sanity_check_vs_median(s)
        self.assertFalse(ok)
        self.assertIn("VERİ HATASI", reason)

    def test_mislabeled_pence_as_usd_would_quarantine(self):
        bad = pd.Series([470.0] * 199 + [47000.0])
        ok, reason, _ = sanity_check_vs_median(bad)
        self.assertFalse(ok)

    def test_lse_magnitude_catches_sub_one_gbp(self):
        ok, reason = sanity_check_lse_magnitude("VUSA.L", pd.Series([1.18] * 100))
        self.assertFalse(ok)
        self.assertIn("çifte GBX", reason)

    def test_tablo_fiyat_call_sites_require_quote_currency(self):
        """
        Çağrı yeri envanteri — sembol= ile tablo_fiyat quote_currency olmadan patlar.
        Geçerli: tefas_ui/favoriler tefas (sembol yok), THYAO quote_currency=TRY.
        Düzeltildi: favoriler_ui hisse/endeks, app _hisse_tablo_fiyat, portfoy _fmt_seviye/_fmt_poz_birim.
        """
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(533.44, "EUR", 38.0, 41.0, sembol="EQQQ.L", gbp_usd=1.34, eur_usd=1.08)
        with self.assertRaises(MissingQuoteCurrencyError):
            tablo_fiyat(79.0, "EUR", 38.0, 41.0, sembol="VUSA.L", gbp_usd=1.34, eur_usd=1.08)


if __name__ == "__main__":
    unittest.main()
