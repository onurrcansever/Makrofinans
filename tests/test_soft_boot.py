# -*- coding: utf-8 -*-
"""Soft açılış + oturum KAP — disk unlock ve non-blocking boot."""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from boot_ui import BOOT_STAGES, render_boot_strip


class SoftBootDiskTest(unittest.TestCase):
    def test_disk_boot_hazir_true_when_makro_and_tarama(self):
        from boot_sequence import disk_boot_hazir

        tahsis = MagicMock()
        tahsis.rejim.rejim = "NOTR"
        with patch(
            "disk_onbellek.disk_getir",
            return_value=(MagicMock(), 60.0),
        ), patch(
            "allocation_engine.tahsis_hesapla", return_value=tahsis
        ), patch(
            "disk_onbellek.disk_mtime", return_value=time.time()
        ):
            self.assertTrue(disk_boot_hazir())

    def test_disk_boot_hazir_false_when_tarama_missing(self):
        from boot_sequence import disk_boot_hazir

        tahsis = MagicMock()
        tahsis.rejim.rejim = "NOTR"
        with patch(
            "disk_onbellek.disk_getir",
            return_value=(MagicMock(), 60.0),
        ), patch(
            "allocation_engine.tahsis_hesapla", return_value=tahsis
        ), patch(
            "disk_onbellek.disk_mtime", return_value=0.0
        ):
            self.assertFalse(disk_boot_hazir())

    def test_disk_boot_hazir_true_demo_makro_only(self):
        # Demo modda tarama anında üretilir — makro diski yeterli.
        from boot_sequence import disk_boot_hazir

        with patch(
            "disk_onbellek.disk_getir",
            return_value=(MagicMock(), 60.0),
        ):
            self.assertTrue(disk_boot_hazir(canli=False))

    def test_disk_boot_hazir_false_when_empty(self):
        from boot_sequence import disk_boot_hazir

        with patch("disk_onbellek.disk_getir", return_value=(None, None)):
            self.assertFalse(disk_boot_hazir())

    def test_disk_boot_hazir_false_when_too_old(self):
        from boot_sequence import SOFT_MAX_BAYAT_SN, disk_boot_hazir

        with patch(
            "disk_onbellek.disk_getir",
            return_value=(MagicMock(), SOFT_MAX_BAYAT_SN + 10),
        ):
            self.assertFalse(disk_boot_hazir())


class SoftBootQuotesTest(unittest.TestCase):
    def test_soft_quotes_uses_daemon_not_blocking_refresh(self):
        from boot_sequence import _new_ctx, advance_boot

        snap = MagicMock()
        snap.veri.eur_try = 53.0
        tahsis = MagicMock()
        tahsis.rejim.rejim = "NOTR"

        ctx = _new_ctx(
            canli=True, force=False, soft=True,
            profil_risk="orta", profil_vade="orta", use_signal_v2=True,
        )
        # fx
        with patch("app_veri.cds_kaynak_ozet", return_value={"ok": True}), \
             patch("app_veri.veri_cek", return_value=snap), \
             patch("allocation_engine.tahsis_hesapla", return_value=tahsis):
            ctx = advance_boot(ctx)
        self.assertEqual(ctx["phase"], "quotes")

        refresh = MagicMock()
        daemon = MagicMock(return_value=True)
        with patch("signal_engine.data.live_quote.load_live_quotes_disk"), \
             patch(
                 "signal_engine.data.live_quote.live_quotes_cache_age_sec",
                 return_value=99999,
             ), \
             patch("background_cache.refresh_live_quotes_quiet", refresh), \
             patch("background_cache.ensure_quotes_daemon", daemon), \
             patch("background_cache.universe_quote_symbols", return_value=["AAPL"]):
            ctx = advance_boot(ctx)

        self.assertEqual(ctx["phase"], "scan")
        daemon.assert_called()
        refresh.assert_not_called()
        self.assertTrue(ctx["stages"]["quotes"].get("soft"))


class SoftBootAnalistTest(unittest.TestCase):
    def test_soft_analist_ready_after_one_chunk(self):
        from boot_sequence import _new_ctx, advance_boot

        snap = MagicMock()
        snap.veri.eur_try = 53.0
        snap.veri_kaynak = "yahoo"
        tahsis = MagicMock()
        tahsis.rejim.rejim = "NOTR"
        tarama = MagicMock()
        tarama.hisseler = [MagicMock()]

        ctx = _new_ctx(
            canli=True, force=False, soft=True,
            profil_risk="orta", profil_vade="orta", use_signal_v2=True,
        )

        miss = MagicMock(return_value={"fetched": 12})
        with patch("app_veri.cds_kaynak_ozet", return_value={"ok": True}), \
             patch("app_veri.veri_cek", return_value=snap), \
             patch("allocation_engine.tahsis_hesapla", return_value=tahsis), \
             patch("signal_engine.data.live_quote.load_live_quotes_disk"), \
             patch(
                 "signal_engine.data.live_quote.live_quotes_cache_age_sec",
                 return_value=10,
             ), \
             patch("background_cache.ensure_quotes_daemon", return_value=False), \
             patch("app_veri.tarama_cek", return_value=tarama), \
             patch("app_veri.tarama_yukleniyor", return_value=False), \
             patch(
                 "background_cache.universe_analist_symbols",
                 return_value=[f"S{i}" for i in range(30)],
             ), \
             patch(
                 "background_cache.analist_eksik_semboller",
                 return_value=[f"S{i}" for i in range(30)],
             ), \
             patch("background_cache.analist_hazir_say", return_value=(5, 30)), \
             patch("temel_veri.yukle_cache", return_value={}), \
             patch("temel_veri._cache_taze", return_value=False), \
             patch("background_cache.refresh_analist_misses", miss), \
             patch("background_cache.ensure_analist_batch_daemon") as daemon:
            guard = 0
            while not ctx.get("complete") and guard < 30:
                guard += 1
                ctx = advance_boot(ctx)

        self.assertTrue(ctx.get("complete"))
        self.assertEqual(int(ctx.get("analist_chunks") or 0), 1)
        miss.assert_called_once()
        daemon.assert_called()


class BootStripTest(unittest.TestCase):
    def test_strip_stages_match(self):
        ids = [s[0] for s in BOOT_STAGES]
        self.assertEqual(ids, ["fx", "quotes", "scan", "analist", "ready"])

    def test_render_boot_strip_callable(self):
        # st.html mock — Streamlit olmadan duman testi
        with patch("boot_ui.st") as st_mock:
            render_boot_strip(
                active_id="quotes",
                done_ids=["fx"],
                detail="test",
                pct=22.0,
                counter="1/10",
            )
            st_mock.html.assert_called_once()


class TefasKapSessionTest(unittest.TestCase):
    """İkinci ziyarette daha önce denenmiş kodlar için HTTP yok."""

    def test_oturum_denenen_filtre(self):
        denenen = {"AAA", "BBB"}
        fonlar = [
            MagicMock(kod="AAA", yonetim_ucreti_pct=None),
            MagicMock(kod="BBB", yonetim_ucreti_pct=None),
            MagicMock(kod="CCC", yonetim_ucreti_pct=None),
            MagicMock(kod="DDD", yonetim_ucreti_pct=1.5),
        ]
        eksik = [
            f.kod for f in fonlar
            if f.yonetim_ucreti_pct is None and f.kod not in denenen
        ]
        self.assertEqual(eksik, ["CCC"])


class SoftTefasYukleTest(unittest.TestCase):
    def test_tefas_yukle_noop_when_ready(self):
        from app_onbellek import AppOnbellek, _tefas_yukle

        ham = MagicMock()
        ham.hata = ""
        ob = MagicMock(spec=AppOnbellek)
        ob.tefas_ham = ham

        with patch("app_onbellek.tefas_yukleniyor", return_value=False), \
             patch("app_veri._tefas_getiri_bozuk_mu", return_value=False), \
             patch("app_onbellek.tefas_ham_cek") as cek:
            _tefas_yukle(ob, tick=0)
            cek.assert_not_called()


if __name__ == "__main__":
    unittest.main()
