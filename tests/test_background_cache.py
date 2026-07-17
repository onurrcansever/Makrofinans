# -*- coding: utf-8 -*-
"""Sessiz live-quote disk TTL + analist miss / batch daemon."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from signal_engine.data.live_quote import (
    DISK_TTL_SEC,
    LiveQuote,
    get_live_quote,
    load_live_quotes_disk,
    save_live_quotes_disk,
)


class LiveQuoteDiskTtlTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._td.name, "live.json")
        self._env = patch.dict(os.environ, {"LIVE_QUOTES_CACHE": self.path})
        self._env.start()
        from signal_engine.data import live_quote as lq

        lq._cache.clear()
        lq._fetched_at = 0.0

    def tearDown(self):
        from signal_engine.data import live_quote as lq

        lq._cache.clear()
        lq._fetched_at = 0.0
        self._env.stop()
        self._td.cleanup()

    def _q(self, *, cached_at: float, price: float = 100.0) -> LiveQuote:
        return LiveQuote(
            price=price,
            currency="TRY",
            settlement="TRY",
            timestamp=datetime.now(timezone.utc),
            age_min=0.0,
            previous_close=95.0,
            cached_at=cached_at,
        )

    def test_disk_hit_within_ttl(self):
        now = time.time()
        save_live_quotes_disk({"MGROS.IS": self._q(cached_at=now - 60)})
        from signal_engine.data import live_quote as lq

        lq._cache.clear()
        loaded = load_live_quotes_disk()
        self.assertIn("MGROS.IS", loaded)
        q = get_live_quote("MGROS.IS")
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.price, 100.0)

    def test_disk_miss_after_ttl(self):
        now = time.time()
        payload = {
            "fetched_at": now - DISK_TTL_SEC - 30,
            "quotes": {
                "MGROS.IS": {
                    "price": 100.0,
                    "currency": "TRY",
                    "settlement": "TRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "previous_close": 95.0,
                    "cached_at": now - DISK_TTL_SEC - 30,
                }
            },
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        from signal_engine.data import live_quote as lq

        lq._cache.clear()
        lq._fetched_at = 0.0
        self.assertEqual(load_live_quotes_disk(), {})
        self.assertIsNone(get_live_quote("MGROS.IS"))

    def test_allow_stale_reads_past_ttl(self):
        now = time.time()
        payload = {
            "fetched_at": now - DISK_TTL_SEC - 60,
            "quotes": {
                "CSCO": {
                    "price": 109.66,
                    "currency": "USD",
                    "settlement": "USD",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "previous_close": 111.77,
                    "cached_at": now - DISK_TTL_SEC - 60,
                }
            },
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        from signal_engine.data import live_quote as lq

        lq._cache.clear()
        self.assertIsNone(get_live_quote("CSCO"))
        q = get_live_quote("CSCO", allow_stale=True)
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.previous_close, 111.77)

    def test_keep_disk_preserves_son_kayit(self):
        from signal_engine.data.live_quote import clear_live_quote_cache

        now = time.time()
        save_live_quotes_disk({"CSCO": self._q(cached_at=now - 30, price=109.66)})
        self.assertTrue(os.path.isfile(self.path))
        clear_live_quote_cache(keep_disk=True)
        from signal_engine.data import live_quote as lq

        self.assertEqual(lq._cache, {})
        self.assertTrue(os.path.isfile(self.path))
        q = get_live_quote("CSCO")
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.price, 109.66)


class AnalistMissSelectTest(unittest.TestCase):
    def test_selects_missing_and_stale(self):
        from background_cache import analist_eksik_semboller

        bugun = date.today().isoformat()
        eski = (date.today() - timedelta(days=2)).isoformat()
        cache = {
            "AAA.IS": {
                "guncelleme": bugun,
                "recommendationKey": "buy",
                "al_sayi": 5,
                "toplam_analist": 10,
            },
            "BBB.IS": {"guncelleme": eski, "recommendationKey": "buy", "al_sayi": 1},
            "CCC.IS": {"guncelleme": bugun, "_bos": True},
            "EEE.IS": {"guncelleme": bugun, "trailingPE": 10.0},  # taze ama analist yok
        }
        need = analist_eksik_semboller(
            ["AAA.IS", "BBB.IS", "CCC.IS", "DDD.IS", "EEE.IS"], cache=cache,
        )
        self.assertNotIn("AAA.IS", need)
        self.assertIn("BBB.IS", need)
        self.assertIn("CCC.IS", need)
        self.assertIn("DDD.IS", need)
        self.assertIn("EEE.IS", need)

    def test_batch_daemon_limits_wave(self):
        import background_cache as bc

        with patch.object(bc, "refresh_analist_misses") as mock_ref:
            with patch.object(
                bc, "analist_eksik_semboller", return_value=[f"S{i}.IS" for i in range(40)],
            ):
                with bc._analist_lock:
                    bc._analist_running = False
                t0 = time.time()
                started = bc.ensure_analist_batch_daemon(
                    [f"S{i}.IS" for i in range(40)], batch_size=12,
                )
                self.assertTrue(started)
                self.assertLess(time.time() - t0, 0.5)
                deadline = time.time() + 2.0
                while time.time() < deadline and not mock_ref.called:
                    time.sleep(0.05)
                mock_ref.assert_called()
                kwargs = mock_ref.call_args.kwargs
                self.assertEqual(kwargs.get("batch_limit"), 12)


if __name__ == "__main__":
    unittest.main()
