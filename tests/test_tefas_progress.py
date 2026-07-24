# -*- coding: utf-8 -*-
"""TEFAS ilerleme durumu."""
from __future__ import annotations

import unittest

from tefas_progress import (
    TEFAS_STAGES,
    progress_ayarla,
    progress_baslat,
    progress_bitir,
    progress_durum,
)


class TefasProgressTest(unittest.TestCase):
    def test_stages_order(self):
        ids = [s[0] for s in TEFAS_STAGES]
        self.assertEqual(
            ids, ["disk", "fetch", "returns", "dagilim", "yaz", "ready"],
        )

    def test_progress_lifecycle(self):
        progress_baslat(detail="başla", zorla=True)
        st = progress_durum()
        self.assertTrue(st["active"])
        self.assertEqual(st["phase"], "disk")

        # İkinci baslat sıfırlamasın
        self.assertFalse(progress_baslat(detail="poll"))
        self.assertEqual(progress_durum()["detail"], "başla")

        progress_ayarla("fetch", "API…", counter="120g")
        st = progress_durum()
        self.assertEqual(st["phase"], "fetch")
        self.assertIn("disk", st["done_ids"])
        self.assertEqual(st["counter"], "120g")

        progress_ayarla("returns", "getiri", pct=60.0)
        self.assertAlmostEqual(progress_durum()["pct"], 60.0)

        progress_bitir(detail="ok")
        st = progress_durum()
        self.assertFalse(st["active"])
        self.assertEqual(st["phase"], "ready")
        self.assertAlmostEqual(st["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
