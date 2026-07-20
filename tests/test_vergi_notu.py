# -*- coding: utf-8 -*-
"""Vergi notu — metin sözleşmesi (hesap motoru değil)."""
from __future__ import annotations

import unittest

from vergi_notu import (
    BIST_OZET,
    BRUT_UYARI,
    MEVDUAT_OZET,
    TEFAS_OZET,
    YABANCI_OZET,
    vergi_notu_caption,
    vergi_notu_html_blok,
    vergi_notu_markdown,
    vergi_notu_rapor_satirlari,
)


class VergiNotuSozlesmeTest(unittest.TestCase):
    def test_bist_sifir_stopaj(self):
        self.assertIn("%0", BIST_OZET)
        self.assertIn("BIST", BIST_OZET)

    def test_tefas_iktisap_tarihine_bagli(self):
        self.assertIn("iktisap", TEFAS_OZET.lower())
        md = vergi_notu_markdown()
        self.assertIn("iktisap", md.lower())

    def test_yabanci_hesaplanmaz(self):
        self.assertIn("hesaplanmaz", YABANCI_OZET)
        self.assertIn("hesaplanmaz", vergi_notu_caption("yabanci"))

    def test_mevduat_net(self):
        self.assertIn("net", MEVDUAT_OZET.lower())
        self.assertIn("stopaj", MEVDUAT_OZET.lower())
        self.assertIn("net", vergi_notu_caption("mevduat").lower())

    def test_brut_uyari_genel(self):
        self.assertIn("brüt", BRUT_UYARI.lower())
        self.assertIn("vergi düşülmez", vergi_notu_caption("genel"))

    def test_rapor_satirlari_ve_html(self):
        satirlar = vergi_notu_rapor_satirlari(max_satir=6)
        self.assertGreaterEqual(len(satirlar), 4)
        joined = " ".join(satirlar)
        self.assertIn("%0", joined)
        self.assertIn("iktisap", joined.lower())
        html = vergi_notu_html_blok()
        self.assertIn("2026", html)
        self.assertIn("BIST", html)
        self.assertIn("<li>", html)


if __name__ == "__main__":
    unittest.main()
