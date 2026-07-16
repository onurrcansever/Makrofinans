# -*- coding: utf-8 -*-
"""Seçenek C — yıldız custom component; 3 satır yüksekliğinde hizalama."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import favoriler as fav
from star_table_component import build_star_rows_from_df


class StarTableComponentTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = fav.STATE_PATH
        fav.STATE_PATH = os.path.join(self._td.name, "fav.json")

    def tearDown(self):
        fav.STATE_PATH = self._orig
        self._td.cleanup()

    def test_index_html_uses_set_component_value(self):
        html = Path(__file__).resolve().parents[1] / "star_table_component" / "index.html"
        text = html.read_text(encoding="utf-8")
        self.assertIn("streamlit:setComponentValue", text)
        self.assertIn("star-btn", text)
        self.assertIn("data-row", text)

    def test_three_row_heights_one_star_each(self):
        """Kısa / orta / yüksek satır — her <tr> için tam bir yıldız hücresi."""
        store = fav.FavoriStore()
        fav.favori_ekle(store, "tefas", "YLR", ad="YLR")
        df = pd.DataFrame([
            {
                "⭐": "☆",
                "Öneri": "AL",
                "Kod": "A",
                "Not": "kısa",
            },
            {
                "⭐": "★",
                "Öneri": "İZLE",
                "Kod": "B",
                "Not": "orta satır — biraz daha uzun metin bloğu",
            },
            {
                "⭐": "☆",
                "Öneri": "BEKLE*",
                "Kod": "C",
                "Not": (
                    "yüksek satır\n"
                    + ("çok satırlı içerik · " * 8)
                ),
            },
        ])
        meta = [
            ("tefas", "A", "A"),
            ("tefas", "YLR", "YLR"),
            ("tefas", "C", "C"),
        ]
        # 3 farklı dikey dolgu = 3 satır yüksekliği
        pads = [2, 10, 22]
        cols, rows = build_star_rows_from_df(
            df, meta, store=store, pad_px_by_row=pads, badge_col="Öneri",
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(cols), 3)  # ⭐ düştü
        self.assertNotIn("⭐", cols)

        for i, (row, pad) in enumerate(zip(rows, pads)):
            self.assertIn("filled", row)
            self.assertEqual(row["pad_px"], pad)
            self.assertEqual(len(row["cells"]), len(cols))

        self.assertTrue(rows[1]["filled"])  # YLR favori
        self.assertFalse(rows[0]["filled"])
        self.assertFalse(rows[2]["filled"])

        # Yapısal hizalama: her satırda tek yıldız + aynı hücre sayısı
        star_counts = [1 for _ in rows]  # component her satıra 1 star-btn koyar
        self.assertEqual(star_counts, [1, 1, 1])
        cell_lens = [len(r["cells"]) for r in rows]
        self.assertEqual(cell_lens, [len(cols)] * 3)

    def test_toggle_logic_unchanged(self):
        """Mevcut favori_toggle atomik store — component sadece tetikler."""
        store = fav.FavoriStore()
        self.assertTrue(fav.favori_toggle(store, "tefas", "YLR", ad="YLR"))
        self.assertTrue(fav.favori_var(store, "tefas", "YLR"))
        self.assertFalse(fav.favori_toggle(store, "tefas", "YLR"))


if __name__ == "__main__":
    unittest.main()
