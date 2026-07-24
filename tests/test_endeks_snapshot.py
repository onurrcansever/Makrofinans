# -*- coding: utf-8 -*-
"""Endeks snapshot — EndeksAI prompt verisi."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from signal_engine.explain.endeks_snapshot import (
    LEJANT,
    build_endeks_snapshot,
)


def _e(**kw):
    base = dict(
        ad="BIST 100",
        sembol="XU100.IS",
        aksiyon_etiket="Azalt",
        guven=71,
        kurulum="Zayıf momentum",
        platform="TR",
        degisim_1ay=-5.0,
        degisim_3ay=-3.0,
        teknik_aksiyon_etiket="Azalt",
        makro_chip="",
        gerekce="Ağırlığı azalt",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class EndeksSnapshotTest(unittest.TestCase):
    def test_bist_azalt_abd_koru_prompt(self):
        rows = [
            _e(),
            _e(
                ad="S&P 500",
                sembol="^GSPC",
                aksiyon_etiket="Koru",
                guven=75,
                kurulum="Trend devam",
                platform="ABD",
                degisim_1ay=0.9,
                degisim_3ay=8.5,
                gerekce="Mevcut ağırlığı koru",
            ),
        ]
        snap = build_endeks_snapshot(
            rows,
            oncelik="Bugün bakılacak yer: **ABD** (BIST’ten göreli daha güçlü).",
            gosterim_pb="EUR",
            makro_rejim="TL_FIRSAT",
            gosterim_getiriler={
                "XU100.IS": {"1a": -6.26, "3a": -4.05},
                "^GSPC": {"1a": 0.91, "3a": 8.52},
            },
            nedenler={
                "XU100.IS": "Ağırlığı azalt (zayıf momentum).",
                "^GSPC": "Grafik uygun; tut.",
            },
        )
        block = snap.prompt_block()
        self.assertIn("ABD", block)
        self.assertIn("Azalt", block)
        self.assertIn("Koru", block)
        self.assertIn("pozisyon ağırlığı", LEJANT.lower())
        self.assertIn(LEJANT[:40], block)
        self.assertIn("EUR", block)
        self.assertIn("-6.3%", block.replace("−", "-") or block)
        self.assertIn("XU100.IS", block)
        self.assertTrue(len(snap.cache_fingerprint()) >= 8)

    def test_lejant_hisse_ayri(self):
        self.assertIn("İZLE değildir", LEJANT)
        self.assertIn("iptal etmez", LEJANT)


if __name__ == "__main__":
    unittest.main()
