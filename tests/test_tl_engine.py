# -*- coding: utf-8 -*-
"""TL karar motoru v2 — duygu, histerezis, explain testleri."""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

import config
from decision_engine import PiyasaVerisi
from gate_hysteresis import (
    CDS_DUSURME_ESIK,
    CDS_YUKSELTME_ESIK,
    KRITIK_VETO_TAVAN,
    cds_tavan_histerezis,
    haber_kriz_histerezis,
)
from macro_data import MacroSnapshot
from news_sentiment import (
    baslik_skoru,
    etkin_haber_sayisi,
    haberleri_analiz_et,
    kritik_veto_aktif,
)
from news_sentiment_scan import SentimentPaketi
from regime_hysteresis import rejim_skoru_hesapla, rejim_tespit_v2, skordan_rejim
from tl_decision_explain import explain_tl_decision
from tl_engine import tl_karar_hesapla
from siyasi_etkin import kap1_haber_sayisi, siyasi_kriz_mi


def _state_tmp(testcase):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "state.json")
    os.environ["TL_ENGINE_STATE_PATH"] = path
    config.TL_ENGINE_STATE_PATH = path
    import gate_hysteresis as gh
    import regime_hysteresis as rh

    gh.STATE_PATH = path
    rh.STATE_PATH = path
    testcase.addCleanup(lambda: os.environ.pop("TL_ENGINE_STATE_PATH", None))


def _veri(cds=240.0, eur=35.0):
    return PiyasaVerisi(
        eur_try=eur,
        usd_try=32.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=cds,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=10,
        savas_risk_makale_sayisi=5,
        savas_risk_guvenilir=True,
    )


class DuyguTest(unittest.TestCase):
    def test_istifa_negatif(self):
        self.assertEqual(baslik_skoru("TCMB başkanı istifa etti"), -1.0)

    def test_rekor_pozitif(self):
        self.assertEqual(baslik_skoru("BIST rekor kırdı"), 0.5)

    def test_notr(self):
        self.assertEqual(baslik_skoru("hava güneşli"), 0.0)

    def test_domine_kurali(self):
        self.assertEqual(
            baslik_skoru("rekor yükselişin ardından soruşturma"),
            -1.0,
        )

    def test_etkin_haber_formulu(self):
        self.assertEqual(etkin_haber_sayisi(51, -0.4), 71)


class DedupeVetoTest(unittest.TestCase):
    def test_dedupe_kritik(self):
        basliklar = ["TCMB başkanı istifa etti - NTV"] * 5
        sonuc = haberleri_analiz_et(basliklar)
        self.assertEqual(sonuc.kritik_neg_sayisi, 1)

    def test_veto_uc_farkli_kaynak(self):
        basliklar = [
            "TCMB başkanı istifa etti - NTV",
            "Kayyum atandı belediyeye - Sözcü",
            "Gözaltına alındı milletvekili - Habertürk",
        ]
        sonuc = haberleri_analiz_et(basliklar)
        self.assertTrue(kritik_veto_aktif(sonuc))
        paket = tl_karar_hesapla(
            _veri(),
            sentiment=SentimentPaketi(
                siyasi=sonuc,
                jeopolitik=haberleri_analiz_et([]),
                etkin_siyasi=3,
                etkin_jeopolitik=0,
                kap1_siyasi=3,
                kritik_veto=True,
                veto_basliklari=["a"],
            ),
            canli_sentiment=False,
        )
        self.assertLessEqual(paket.sonuc.tavan_oran, KRITIK_VETO_TAVAN + 0.001)


class HisterezisTest(unittest.TestCase):
    def setUp(self):
        _state_tmp(self)

    def test_cds_histerezis(self):
        ham = 0.50
        t1, _ = cds_tavan_histerezis(255, ham)
        self.assertLess(t1, ham)
        t2, _ = cds_tavan_histerezis(245, ham)
        self.assertEqual(t2, t1)
        t3, _ = cds_tavan_histerezis(225, ham)
        self.assertGreaterEqual(t3, t2)

    def test_haber_kriz_histerezis(self):
        aktif, _ = haber_kriz_histerezis(90)
        self.assertTrue(aktif)
        aktif2, _ = haber_kriz_histerezis(75)
        self.assertTrue(aktif2)
        aktif3, _ = haber_kriz_histerezis(65)
        self.assertFalse(aktif3)


class RejimTeyitTest(unittest.TestCase):
    def setUp(self):
        _state_tmp(self)

    def test_tek_cekimde_rejim_degismez(self):
        veri = _veri(cds=300)
        veri.siyasi_risk_makale_sayisi = 50
        snap = MacroSnapshot(
            veri=veri,
            vix=22,
            enflasyon_tr_yillik=40,
            eur_usd=1.08,
        )
        with patch("regime_hysteresis.rejim_skoru_hesapla", return_value=20.0):
            with patch("regime_hysteresis.rejim_tespit", wraps=__import__("regime").rejim_tespit) as mock_ham:
                r1 = rejim_tespit_v2(snap, etkin_siyasi=5)
                ham_rejim = mock_ham.return_value.rejim
                if ham_rejim == "TL_FIRSAT":
                    self.skipTest("Ham rejim zaten TL_FIRSAT — farklı snapshot gerekir")
                self.assertNotEqual(r1.rejim, "TL_FIRSAT")
                r2 = rejim_tespit_v2(snap, etkin_siyasi=5)
                self.assertEqual(r2.rejim, "TL_FIRSAT")


class SiyasiEtkinTest(unittest.TestCase):
    def test_spekulasyon_sisi_kriz_tetiklemez(self):
        """Negatif duygu etkin sayıyı şişirse bile ham düşükse kriz yok."""
        self.assertEqual(kap1_haber_sayisi(51, 125), 51)
        self.assertFalse(siyasi_kriz_mi(51, 125))

    def test_sorgu_birlestirme_siniri(self):
        """Ham 83 + etkin 91 birleşik sayım artefaktı — kriz eşiği 85 altında kalmalı."""
        self.assertFalse(siyasi_kriz_mi(83, 91))

    def test_gercek_kriz_ham_yuksek(self):
        self.assertTrue(siyasi_kriz_mi(90, 90))


class ExplainTest(unittest.TestCase):
    def setUp(self):
        _state_tmp(self)

    def test_explain_tutarlilik(self):
        veri = _veri(cds=221, eur=40.0)
        bos = haberleri_analiz_et([])
        sent = SentimentPaketi(
            siyasi=bos,
            jeopolitik=bos,
            etkin_siyasi=10,
            etkin_jeopolitik=5,
            kap1_siyasi=10,
            kritik_veto=False,
            veto_basliklari=[],
        )
        ex = explain_tl_decision(
            veri,
            vade_gun=config.KALAN_GUN,
            sentiment=sent,
            reel_pp=4.0,
            allocation_pay=0.20,
        )
        self.assertAlmostEqual(ex.nihai_pay_pct, 20.0, delta=0.15)
        self.assertTrue(ex.baglayici_kisit)


if __name__ == "__main__":
    unittest.main()
