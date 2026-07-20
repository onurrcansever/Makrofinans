# -*- coding: utf-8 -*-
"""temel_veri finansal DataFrame satır eşlemesi."""
import unittest

import pandas as pd

from temel_veri import _df_cell, _fetch_finansal_ozet


class TemelFinansParseTest(unittest.TestCase):
    def test_df_cell_esnek_ad(self):
        df = pd.DataFrame(
            {"2024": [100.0, 10.0], "2023": [90.0, 8.0]},
            index=["Total Revenue", "Net Income"],
        )
        self.assertEqual(_df_cell(df, ("Total Revenue",), 0), 100.0)
        self.assertEqual(_df_cell(df, ("Total Revenue",), 1), 90.0)
        self.assertEqual(_df_cell(df, ("Net Income",), 0), 10.0)

    def test_fetch_finansal_ozet_mock(self):
        class _T:
            financials = pd.DataFrame(
                {"a": [200.0, 20.0], "b": [180.0, 15.0]},
                index=["Total Revenue", "Net Income"],
            )
            quarterly_financials = pd.DataFrame(
                {"q": [50.0, 5.0]},
                index=["Total Revenue", "Net Income"],
            )
            cashflow = pd.DataFrame(
                {"a": [12.0, -3.0, 1.0]},
                index=["Free Cash Flow", "Investing Cash Flow", "Financing Cash Flow"],
            )
            quarterly_cashflow = None
            balance_sheet = pd.DataFrame(
                {"a": [500.0, 200.0]},
                index=["Total Assets", "Total Liabilities Net Minority Interest"],
            )
            quarterly_balance_sheet = None

        out = _fetch_finansal_ozet(_T())
        self.assertEqual(out["revenue_y"], 200.0)
        self.assertEqual(out["revenue_y_prev"], 180.0)
        self.assertEqual(out["net_income_y"], 20.0)
        self.assertEqual(out["fcf_y"], 12.0)
        self.assertEqual(out["total_assets_y"], 500.0)
        self.assertAlmostEqual(out["profit_margin_y"], 0.1)
        self.assertIn("finans_guncelleme", out)


if __name__ == "__main__":
    unittest.main()
