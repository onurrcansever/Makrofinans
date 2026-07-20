# -*- coding: utf-8 -*-
"""P0 güvenilirlik — fırsat=v2 AL, WATCH→BEKLE, makro tavan, hikaye, kriz TL=0."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from allocation_engine import _rebalance_deadband, tahsis_hesapla
from investor_profile import YatirimProfili, profil_skor_ayari, profil_sinirlari
from macro_data import demo_snapshot
from portfoy_yoneticisi import _yonetici_v2_uygula, yonetici_oncelikli
from signal_engine.pipeline import _makro_karar_tavan, _map_alim_uygun
from stock_scanner import HisseAnaliz, _firsatlari_sec, _hikaye_uret


def _h(**kw):
    base = dict(
        sembol="AAPL",
        ad="Apple",
        piyasa="NASDAQ",
        fiyat=200.0,
        degisim_1g=0.0,
        degisim_1ay=-1.0,
        degisim_3ay=5.0,
        degisim_1y=20.0,
        rsi=40.0,
        sma20=198.0,
        sma50=190.0,
        sma200=170.0,
        sinyal="ALIM_FIRSATI",
        skor=70.0,
        gerekce="test",
        sektor="teknoloji",
        bilesik_skor=72.0,
    )
    base.update(kw)
    fields = HisseAnaliz.__dataclass_fields__
    return HisseAnaliz(**{k: base[k] for k in base if k in fields})


class FirsatV2Test(unittest.TestCase):
    def test_v2_sadece_buy(self):
        al = _h(sembol="AL1", signal_v2_code="BUY", bilesik_skor=80)
        izle = _h(sembol="IZ1", signal_v2_code="WATCH", sinyal="ALIM_FIRSATI", bilesik_skor=90)
        # v1 alanları izle'de fırsat gibi — v2 filtresi dışlamalı
        out = _firsatlari_sec([al, izle], 55, v2=True)
        self.assertEqual([h.sembol for h in out], ["AL1"])

    def test_v1_eski_davranis(self):
        a = _h(sembol="A", sinyal="ALIM_FIRSATI", bilesik_skor=80)
        b = _h(sembol="B", sinyal="BEKLE", bilesik_skor=90)
        out = _firsatlari_sec([a, b], 55, v2=False)
        self.assertEqual([h.sembol for h in out], ["A"])


class YoneticiWatchTest(unittest.TestCase):
    def test_watch_trending_down_bekle(self):
        h = _h(
            signal_v2_code="WATCH",
            signal_v2_decision="İZLE",
            signal_v2_regime="TRENDING_DOWN",
            signal_v2_decision_gates=["Rejim TRENDING_DOWN: AL/GÜÇLÜ AL → İZLE"],
        )
        _yonetici_v2_uygula(h)
        self.assertEqual(h.yonetici_aksiyon, "BEKLE")
        self.assertNotEqual(h.yonetici_aksiyon, "KADEMELI")

    def test_oncelikli_sadece_al(self):
        al = _h(sembol="AL", signal_v2_code="BUY", yonetici_aksiyon="AL", bilesik_skor=70)
        watch = _h(
            sembol="W", signal_v2_code="WATCH", yonetici_aksiyon="BEKLE", bilesik_skor=99,
        )
        _yonetici_v2_uygula(al)
        _yonetici_v2_uygula(watch)
        top = yonetici_oncelikli([al, watch], n=5)
        self.assertTrue(all(getattr(h, "yonetici_aksiyon") == "AL" for h in top))


class MakroTavanTest(unittest.TestCase):
    def test_kriz_buy_to_watch(self):
        gates = []
        self.assertEqual(_makro_karar_tavan("BUY", "KRIZ", gates), "WATCH")
        self.assertTrue(any("KRIZ" in g for g in gates))

    def test_notr_buy_kalir(self):
        gates = []
        self.assertEqual(_makro_karar_tavan("BUY", "NOTR", gates), "BUY")

    def test_map_watch_izle(self):
        self.assertEqual(_map_alim_uygun("WATCH"), "IZLE")


class HikayeTest(unittest.TestCase):
    def test_izle_kademeli_yok(self):
        h = _h(signal_v2_code="WATCH", signal_v2_decision="İZLE", sinyal="ALIM_FIRSATI")
        hik = _hikaye_uret(h)
        self.assertNotIn("kademeli alım bölgesi", hik.lower())
        self.assertIn("alım hikayesi yok", hik.lower())


class TahsisGuvenTest(unittest.TestCase):
    def test_kriz_sablon_tl_sifir(self):
        """KRİZ şablonunda yüksek riskte bile TL=0 (Kapı 1 ile tutarlı)."""
        from regime import RejimSonucu

        snap = demo_snapshot()
        kriz = RejimSonucu(
            rejim="KRIZ",
            etiket="KRİZ",
            aciklama="test kriz",
            guven=0.9,
            adimlar=["test"],
        )
        sonuc = SimpleNamespace(
            tavan_oran=0.0,
            kapi1_gecti=False,
            adimlar=["Kapı1 kapalı"],
            uyarilar=[],
        )
        paket = SimpleNamespace(
            sonuc=sonuc,
            sentiment=SimpleNamespace(
                etkin_siyasi=99, siyasi=SimpleNamespace(haber_sayisi=99),
            ),
            kritik_veto=True,
            ppk_bekle=False,
            ppk_notu="",
        )

        with patch("allocation_engine.rejim_tespit", return_value=kriz), \
             patch("allocation_engine.tl_karar_hesapla", return_value=paket), \
             patch("allocation_engine.sentiment_tara") as m_sent, \
             patch("allocation_engine.siyasi_sayim_raporla"), \
             patch("allocation_engine.explain_tl_decision") as m_ex, \
             patch("allocation_engine.explain_to_dict", return_value=[]):
            m_sent.return_value = SimpleNamespace(
                etkin_siyasi=99, siyasi=SimpleNamespace(haber_sayisi=99),
            )
            m_ex.return_value = SimpleNamespace(
                baglayici_kisit="Kapı1", baglayici_etiket="Kapı 1",
                oneri_cumlesi="TL yok", adimlar=[],
            )
            tahsis = tahsis_hesapla(
                snap, YatirimProfili(risk="yuksek", vade="orta"), ham_rejim=True,
            )
        self.assertEqual(tahsis.agirliklar.get("tl_deposit", 0), 0.0)
        self.assertEqual(tahsis.agirliklar.get("bist", 0), 0.0)
        self.assertEqual(tahsis.agirliklar.get("crypto", 0), 0.0)

    def test_deadband(self):
        eski = {k: 1 / 7 for k in (
            "eur_cash", "usd_cash", "tl_deposit", "gold", "silver", "bist", "crypto"
        )}
        yeni = dict(eski)
        yeni["eur_cash"] += 0.01
        yeni["gold"] -= 0.01
        out, koru = _rebalance_deadband(yeni, eski, 0.03)
        self.assertTrue(koru)
        self.assertAlmostEqual(out["eur_cash"], eski["eur_cash"], places=5)

    def test_amac_skor(self):
        koruma = profil_skor_ayari(YatirimProfili(amac="sermaye_koruma"))
        buyume = profil_skor_ayari(YatirimProfili(amac="buyume", risk="orta"))
        self.assertGreater(koruma["eur_cash"], buyume["eur_cash"])
        self.assertGreater(buyume["bist"], koruma["bist"])

    def test_amac_sinir(self):
        _, max_k, _, _ = profil_sinirlari(YatirimProfili(risk="orta", amac="sermaye_koruma"))
        _, max_b, _, _ = profil_sinirlari(YatirimProfili(risk="orta", amac="buyume"))
        self.assertLessEqual(max_k["bist"], max_b["bist"])


if __name__ == "__main__":
    unittest.main()
