# -*- coding: utf-8 -*-
"""Temel veri katmanı — cache, timeout, atomik yazma, ETF, EUR hedef."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import temel_veri as tv


class TemelVeriTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = tv.STATE_PATH
        tv.STATE_PATH = os.path.join(self._td.name, "temel_veri_cache.json")

    def tearDown(self):
        tv.STATE_PATH = self._orig
        self._td.cleanup()

    def test_cache_ttl_no_refetch_same_day(self):
        calls = {"n": 0}

        def fake(sym):
            calls["n"] += 1
            return {
                "trailingPE": 22.0,
                "recommendationKey": "buy",
                "currency": "TRY",
                "guncelleme": date.today().isoformat(),
            }

        with patch.object(tv, "_fetch_one_info", side_effect=fake):
            tv.temel_veri_cek(["BIMAS.IS"], force=True)
            n1 = calls["n"]
            cache, stats = tv.temel_veri_cek(["BIMAS.IS"], force=False)
            self.assertEqual(calls["n"], n1)
            self.assertEqual(stats["cache_hit"], 1)
            self.assertIn("BIMAS.IS", cache)

    def test_cache_stale_refetches(self):
        eski = (date.today() - timedelta(days=2)).isoformat()
        tv.kaydet_cache({
            "BIMAS.IS": {"trailingPE": 1.0, "guncelleme": eski},
        })
        calls = {"n": 0}

        def fake(sym):
            calls["n"] += 1
            return {"trailingPE": 22.0, "guncelleme": date.today().isoformat()}

        with patch.object(tv, "_fetch_one_info", side_effect=fake):
            tv.temel_veri_cek(["BIMAS.IS"], force=False)
            self.assertEqual(calls["n"], 1)

    def test_timeout_returns_empty_no_raise(self):
        # İç içe ThreadPool yok — ağ hatası/timeout yumuşak {} döner (Errno 24 önlemi)
        with patch.object(tv, "_fetch_one_info", side_effect=TimeoutError("slow")):
            data = tv._fetch_one_with_timeout("SLOW.IS", timeout=0.2)
        self.assertEqual(data, {})

    def test_atomic_write_preserves_old_on_crash(self):
        tv.kaydet_cache({"AAPL": {"trailingPE": 30.0, "guncelleme": "2026-07-01"}})
        path = tv.STATE_PATH
        with open(path, encoding="utf-8") as f:
            before = f.read()

        def boom_replace(src, dst):
            raise OSError("simulated crash before replace")

        with patch.object(tv.os, "replace", side_effect=boom_replace):
            ok = tv.kaydet_cache({"AAPL": {"trailingPE": 99.0, "guncelleme": "2026-07-16"}})
        self.assertFalse(ok)

        with open(path, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)
        data = json.loads(after)
        self.assertEqual(data["AAPL"]["trailingPE"], 30.0)

    def test_etf_notu_no_error(self):
        notu = tv.temel_veri_notu(
            "EQQQ.L",
            {"quoteType": "ETF", "currency": "GBp", "guncelleme": "2026-07-16"},
            625.0,
            tur="etf",
            eur_try=50.0, usd_try=42.0,
        )
        self.assertEqual(notu["tur"], "etf")
        self.assertIn("ETF", notu["not"])
        self.assertIsNone(notu["fk_trailing"])
        md = tv.format_degerleme_markdown(notu)
        self.assertIn("Değerleme", md)
        self.assertIn("analist konsensüsü yok", md)

    def test_bist_trailing_pe_mock(self):
        mock_info = {
            "trailingPE": 22.06292,
            "forwardPE": 7.45,
            "recommendationKey": "strong_buy",
            "numberOfAnalystOpinions": 12,
            "targetMeanPrice": 480.0,
            "currency": "TRY",
            "earningsGrowth": 0.12,
            "guncelleme": "2026-07-16",
        }
        with patch.object(tv, "_fetch_one_info", return_value=dict(mock_info)):
            cache, _ = tv.temel_veri_cek(["BIMAS.IS"], force=True)
        self.assertAlmostEqual(cache["BIMAS.IS"]["trailingPE"], 22.06292, places=2)

        notu = tv.temel_veri_notu(
            "BIMAS.IS", cache["BIMAS.IS"], fiyat_eur=480.0 / 50.0,
            tur="hisse", eur_try=50.0, usd_try=42.0,
        )
        self.assertEqual(notu["fk_trailing"], 22.06)
        self.assertEqual(notu["analist"], "strong_buy")
        self.assertEqual(notu["analist_sayi"], 12)

    def test_target_mean_to_eur(self):
        # 315 USD hedef, EURUSD=1.05 → ~300 EUR; fiyat_eur=260 → fark pozitif
        temel = {
            "targetMeanPrice": 315.0,
            "currency": "USD",
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": 40,
            "guncelleme": "2026-07-16",
        }
        notu = tv.temel_veri_notu(
            "MSFT", temel, fiyat_eur=260.0,
            tur="hisse",
            eur_try=52.5, usd_try=50.0, eur_usd=1.05,
        )
        self.assertIsNotNone(notu["hedef_eur"])
        # 315 USD → TL = 315*50, / EURTRY 52.5 → 300 EUR (cross)
        self.assertAlmostEqual(notu["hedef_eur"], 300.0, delta=1.0)
        self.assertAlmostEqual(notu["hedef_fark_pct"], (300 / 260 - 1) * 100, delta=1.0)

    def test_eregl_hedef_fark_uses_live_spot_not_hardcoded_42(self):
        """targetMeanPrice TRY→EUR: kur_tablo_spot EURTRY; fark sabit 42 TRY ile hesaplanmaz."""
        from fiyat_para import pb_cevir

        eur_try = 53.9
        hedef = pb_cevir(38.15, "TL", "EUR", eur_try, 47.0)
        self.assertAlmostEqual(hedef, 0.708, delta=0.002)
        fiyat_eur = 0.8122  # gerçek spot EUR (sabit 42 TRY≠0.779)
        fark = (hedef / fiyat_eur - 1.0) * 100.0
        self.assertAlmostEqual(fark, -12.8, delta=0.3)
        # Sabit 42 yolu yanlış: ~-9.2
        yanlis = (hedef / (42.0 / eur_try) - 1.0) * 100.0
        self.assertAlmostEqual(yanlis, -9.2, delta=0.3)
        self.assertLess(fark, -11.0)

        notu = tv.temel_veri_notu(
            "EREGL.IS",
            {
                "targetMeanPrice": 38.15,
                "currency": "TRY",
                "recommendationKey": "buy",
                "guncelleme": "2026-07-16",
            },
            fiyat_eur=0.8122,
            tur="hisse",
            eur_try=53.9,
            usd_try=47.0,
        )
        self.assertAlmostEqual(notu["hedef_eur"], 0.71, delta=0.01)
        self.assertAlmostEqual(notu["hedef_fark_pct"], -12.8, delta=0.5)

    def test_single_fail_isolated(self):
        def fake(sym):
            if sym == "BAD.IS":
                raise RuntimeError("boom")
            return {"trailingPE": 10.0, "guncelleme": date.today().isoformat()}

        with patch.object(tv, "_fetch_one_info", side_effect=fake):
            cache, stats = tv.temel_veri_cek(["BAD.IS", "GOOD.IS"], force=True)
        self.assertIn("GOOD.IS", cache)
        self.assertAlmostEqual(cache["GOOD.IS"]["trailingPE"], 10.0)
        self.assertTrue(cache.get("BAD.IS", {}).get("_bos") or not cache.get("BAD.IS", {}).get("trailingPE"))

    def test_skor_label_bimas(self):
        self.assertEqual(
            tv.skor_label(59, 73, {
                "tur": "hisse", "analist": "strong_buy",
                "analist_sayi": 14, "al_sayi": 14, "hedef_fark_pct": 37,
            }),
            "59 (73%) 💚14/14 +37%",
        )

    def test_skor_label_msft(self):
        self.assertEqual(
            tv.skor_label(40, 7, {
                "tur": "hisse", "analist": "buy",
                "analist_sayi": 55, "al_sayi": 53, "hedef_fark_pct": 41,
            }),
            "40 (7%) 💚53/55 +41%",
        )

    def test_skor_label_eregl_hold(self):
        self.assertEqual(
            tv.skor_label(59, 77, {
                "tur": "hisse", "analist": "hold",
                "analist_sayi": 13, "al_sayi": 5, "hedef_fark_pct": 2,
            }),
            "59 (77%) 🟡5/13 +2%",
        )

    def test_skor_label_eqqq_etf(self):
        self.assertEqual(tv.skor_label(66, 92, {"tur": "etf"}), "66 (92%)")
        self.assertEqual(tv.skor_label(66, 92, None), "66 (92%)")

    def test_skor_label_al_sayi_none_no_bare_toplam(self):
        # Tek başına toplam yanıltıcı (AL14 ≠ 14/14) — sayı gösterme
        self.assertEqual(
            tv.skor_label(59, 73, {
                "tur": "hisse", "analist": "strong_buy",
                "analist_sayi": 14, "al_sayi": None, "hedef_fark_pct": 37,
            }),
            "59 (73%) 💚 +37%",
        )

    def test_ensure_al_sayi_patches_cache(self):
        tv.kaydet_cache({
            "MSFT": {
                "recommendationKey": "strong_buy",
                "numberOfAnalystOpinions": 55,
                "guncelleme": date.today().isoformat(),
            },
        })
        with patch.object(tv, "_fetch_rec_counts_sembol", return_value={
            "strongBuy": 12, "buy": 41, "hold": 3, "sell": 0, "strongSell": 0,
            "al_sayi": 53,
        }):
            cache = tv.ensure_al_sayi(["MSFT"])
        self.assertEqual(cache["MSFT"]["al_sayi"], 53)
        notu = tv.temel_veri_notu("MSFT", cache["MSFT"], None, tur="hisse")
        self.assertEqual(
            tv.skor_label(40, 7, notu, pdf_safe=True),
            "40 (7%) AL53/55",
        )

    def test_temel_veri_tarama_icin_fills_missing(self):
        def fake(sym):
            return {
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": 10,
                "strongBuy": 3,
                "buy": 5,
                "al_sayi": 8,
                "targetMeanPrice": 100.0,
                "currentPrice": 80.0,
                "currency": "USD",
                "guncelleme": date.today().isoformat(),
            }

        with patch.object(tv, "_fetch_one_info", side_effect=fake):
            cache, stats = tv.temel_veri_tarama_icin(["NEWCO", "OTHER"])
        self.assertIn("NEWCO", cache)
        self.assertEqual(cache["NEWCO"]["al_sayi"], 8)
        self.assertEqual(stats["analistli"], 2)
        self.assertGreaterEqual(stats["fetched"], 2)

    def test_temel_veri_progress_callback(self):
        events = []

        def fake(sym):
            return {
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": 5,
                "al_sayi": 4,
                "strongBuy": 2,
                "buy": 2,
                "guncelleme": date.today().isoformat(),
            }

        def cb(done, total, msg):
            events.append((done, total, msg))

        with patch.object(tv, "_fetch_one_info", side_effect=fake):
            tv.temel_veri_tarama_icin(["AAA", "BBB"], progress_cb=cb)
        self.assertGreaterEqual(len(events), 2)
        self.assertTrue(any("AAA" in m or "BBB" in m for _, _, m in events))
        self.assertEqual(events[-1][2], "Tamamlandı")

    def test_skor_label_pdf_safe(self):
        self.assertEqual(
            tv.skor_label(59, 73, {
                "tur": "hisse", "analist": "strong_buy",
                "analist_sayi": 14, "al_sayi": 14, "hedef_fark_pct": 37,
            }, pdf_safe=True),
            "59 (73%) AL14/14 +37%",
        )
        self.assertEqual(
            tv.skor_label_pdf_safe("59 (73%) 💚14/14 +37%"),
            "59 (73%) AL14/14 +37%",
        )

    def test_temel_veri_notu_al_sayi_from_counts(self):
        notu = tv.temel_veri_notu(
            "BIMAS.IS",
            {
                "recommendationKey": "strong_buy",
                "numberOfAnalystOpinions": 14,
                "strongBuy": 10,
                "buy": 4,
                "currency": "TRY",
                "targetMeanPrice": 500.0,
                "currentPrice": 365.0,
                "guncelleme": "2026-07-16",
            },
            fiyat_eur=None,
            tur="hisse",
        )
        self.assertEqual(notu["al_sayi"], 14)
        self.assertEqual(notu["analist_sayi"], 14)
        self.assertAlmostEqual(notu["hedef_fark_pct"], 37.0, delta=0.5)

    def test_skor_label_deger_kilidi_df(self):
        import pandas as pd

        rows = [
            {"Sembol": "BIMAS.IS", "Skor": 59, "pct": 73},
            {"Sembol": "EQQQ.L", "Skor": 66, "pct": 92},
            {"Sembol": "MSFT", "Skor": 40, "pct": 7},
        ]
        df = pd.DataFrame(rows)
        cols_once = list(df.columns)
        n_once = len(df)
        df = df.copy()
        df["Skor"] = [
            tv.skor_label(59, 73, {
                "tur": "hisse", "analist": "strong_buy",
                "analist_sayi": 14, "al_sayi": 14, "hedef_fark_pct": 37,
            }),
            tv.skor_label(66, 92, {"tur": "etf"}),
            tv.skor_label(40, 7, {
                "tur": "hisse", "analist": "buy",
                "analist_sayi": 55, "al_sayi": 53, "hedef_fark_pct": 41,
            }),
        ]
        self.assertEqual(list(df.columns), cols_once)
        self.assertEqual(len(df), n_once)


if __name__ == "__main__":
    unittest.main()
