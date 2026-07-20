# -*- coding: utf-8 -*-
"""Açılış boot — aşama sırası ve dilimli ilerleme."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from boot_ui import BOOT_STAGES


class BootUiTest(unittest.TestCase):
    def test_stages_order(self):
        ids = [s[0] for s in BOOT_STAGES]
        self.assertEqual(ids, ["fx", "quotes", "scan", "analist", "ready"])


class BootSequenceTest(unittest.TestCase):
    def test_advance_boot_reaches_ready(self):
        from boot_sequence import _new_ctx, advance_boot, boot_ui_state

        snap = MagicMock()
        snap.veri.eur_try = 53.0
        snap.veri_kaynak = "yahoo"
        tahsis = MagicMock()
        tahsis.rejim.rejim = "NOTR"
        tarama = MagicMock()
        tarama.hisseler = [MagicMock()]
        tarama.uyarilar = []

        ctx = _new_ctx(
            canli=True, force=False,
            profil_risk="orta", profil_vade="orta", use_signal_v2=True,
        )

        with patch("app_veri.cds_kaynak_ozet", return_value={"ok": True}), \
             patch("app_veri.veri_cek", return_value=snap), \
             patch("allocation_engine.tahsis_hesapla", return_value=tahsis), \
             patch("signal_engine.data.live_quote.load_live_quotes_disk"), \
             patch(
                 "signal_engine.data.live_quote.live_quotes_cache_age_sec",
                 return_value=10,
             ), \
             patch("app_veri.tarama_cek", return_value=tarama), \
             patch("app_veri.tarama_yukleniyor", return_value=False), \
             patch("background_cache.universe_analist_symbols", return_value=["AAPL"]), \
             patch("background_cache.analist_eksik_semboller", return_value=[]), \
             patch("background_cache.analist_hazir_say", return_value=(1, 1)):
            guard = 0
            while not ctx.get("complete") and guard < 20:
                guard += 1
                ctx = advance_boot(ctx)
                ui = boot_ui_state(ctx)
                self.assertGreaterEqual(ui["pct"], 0)
                self.assertLessEqual(ui["pct"], 100)

        self.assertTrue(ctx.get("complete"))
        self.assertIn("ready", ctx.get("done_ids") or [])
        self.assertAlmostEqual(boot_ui_state(ctx)["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
