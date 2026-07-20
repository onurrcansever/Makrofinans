# -*- coding: utf-8 -*-
"""karar_yorum — baglam + mock LLM."""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch

from karar_yorum import (
    baglam_cache_anahtar,
    karar_ai_yorum,
    karar_baglam_ozeti,
    _build_prompt,
)
from nakit_danisman import NakitPlani, PlanSatiri


def _plan() -> NakitPlani:
    return NakitPlani(
        girilen_tutar=200_000,
        para_birimi="TL",
        tutar_tl=200_000,
        mevcut_toplam_tl=1_000_000,
        yeni_toplam_tl=1_200_000,
        rejim_etiket="TL mevduat fırsatı",
        satirlar=[
            PlanSatiri(
                sinif="tl_deposit",
                etiket="TL mevduat",
                tutar_tl=100_000,
                oran_pct=50,
                mevcut_pct=20,
                hedef_pct=30,
                arac="YK 6 ay",
                gerekce="Reel faiz pozitif",
            ),
            PlanSatiri(
                sinif="gold",
                etiket="Altın",
                tutar_tl=100_000,
                oran_pct=50,
                mevcut_pct=10,
                hedef_pct=15,
                arac="GC=F",
                gerekce="Hedge",
            ),
        ],
        notlar=["Test notu"],
    )


class KararYorumTest(unittest.TestCase):
    def test_baglam_plan_tutar(self):
        b = karar_baglam_ozeti(_plan())
        self.assertEqual(b["plan"]["tutar_tl"], 200000)
        self.assertEqual(len(b["plan"]["satirlar"]), 2)
        self.assertIn("tl_deposit", b["plan"]["satirlar"][0]["sinif"])

    def test_prompt_icerir_tutar(self):
        b = karar_baglam_ozeti(_plan())
        p = _build_prompt(b)
        self.assertIn("200000", p.replace(",", "").replace(" ", ""))
        self.assertIn("TL mevduat", p)
        self.assertIn("Hisse & ETF", p)
        self.assertIn("Bugün için net aksiyon", p)
        self.assertIn("endeksler", p)

    def test_cache_anahtar_stabil(self):
        b = karar_baglam_ozeti(_plan())
        self.assertEqual(baglam_cache_anahtar(b), baglam_cache_anahtar(b))

    def test_ai_yorum_mock(self):
        b = karar_baglam_ozeti(_plan())
        metin, meta = karar_ai_yorum(
            b,
            force=True,
            _call_fn=lambda prompt: "Plan TL mevduat ve altına dengeli dağıtıyor.",
        )
        self.assertIn("mevduat", metin.lower())
        self.assertFalse(meta.get("cache_hit"))
        self.assertFalse(meta.get("hata"))

    def test_no_key_fallback(self):
        b = karar_baglam_ozeti(_plan())
        with patch("karar_yorum.provider_ready", return_value=False):
            metin, meta = karar_ai_yorum(b, force=True)
        self.assertEqual(meta.get("hata"), "no_key")
        self.assertIn("Yorum", metin)


if __name__ == "__main__":
    unittest.main()
