# -*- coding: utf-8 -*-
import unittest

from tefas_dagilim import satirdan_dagilim, _etkin_kategori


class TefasDagilimTest(unittest.TestCase):
    def test_hisse_agirlikli(self):
        row = {"stock_pct": 55.0, "government_bond_pct": 10.0}
        d = satirdan_dagilim(row)
        self.assertEqual(d.etkin_kategori, "hisse")
        self.assertIn("Hisse", d.ozet)

    def test_doviz_agirlikli(self):
        row = {"government_external_debt_pct": 45.0, "private_sector_external_debt_pct": 15.0}
        d = satirdan_dagilim(row)
        self.assertEqual(d.etkin_kategori, "serbest_doviz")

    def test_bono_mevduat(self):
        self.assertEqual(_etkin_kategori(5, 35, 5, 25, 0, 0), "borclanma")


if __name__ == "__main__":
    unittest.main()
