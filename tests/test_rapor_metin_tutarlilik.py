# -*- coding: utf-8 -*-
"""Rapor metin tutarlılığı — şablon sızıntısı, altın alan ayrımı, PDF kesme."""
from __future__ import annotations

import unittest

from market_context import _altin_beklenti, _altin_konum_trend
from report_pdf import _temiz


class AltinBaglamAlanlariTest(unittest.TestCase):
    def test_beklenti_konum_trend_kopyalamaz(self):
        konum, trend = _altin_konum_trend(3300, 3500, 2800, -19.6)
        bek = _altin_beklenti()
        self.assertIn("orta bölge", konum)
        self.assertIn("-19.6%", trend)
        self.assertIn("kademeli alım", trend)
        self.assertNotIn("orta bölge", bek)
        self.assertNotIn("-19.6", bek)
        self.assertIn("Fed", bek)

    def test_temiz_cumle_sinirinda_keser(self):
        uzun = (
            "52 hafta bandının %71 noktasında — orta bölge. "
            "Son 3 ay -19.6% düşüş; kademeli alım düşünülebilir. "
            "Fed ve reel faiz beklentisi altın talebini belirler."
        )
        out = _temiz(uzun, 90)
        self.assertTrue(out.endswith("…"))
        self.assertNotIn("Fed ve…", out)
        self.assertNotRegex(out, r"Fed ve$")


if __name__ == "__main__":
    unittest.main()
