# -*- coding: utf-8 -*-
"""Rejim kapısı, CDS stres yeniden hesabı, altın momentum — tutarlılık testleri."""
import unittest
from unittest.mock import patch

import config
from advice_engine import danisman_raporu_olustur
from allocation_engine import tahsis_hesapla, tl_profil_risk_tavan
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma
from regime import RejimSonucu
from scenario_analysis import _cds_stresi, _kur_soku


def _snap(rejim: str = "NOTR", altin_3m: float = 5.0, cds: float = 250.0):
    veri = PiyasaVerisi(
        eur_try=53.0,
        usd_try=46.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.42,
        cds_5y_bp=cds,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=10,
        savas_risk_makale_sayisi=5,
        savas_risk_guvenilir=True,
    )
    return MacroSnapshot(
        veri=veri,
        vix=18.0,
        enflasyon_tr_yillik=32.0,
        eur_usd=1.08,
        altin_3m_degisim=altin_3m,
        btc_usd=95000.0,
        btc_3m_degisim=10.0,
    )


def _pozitif_mevduat(reel: float = 2.5) -> MevduatKarsilastirma:
    return MevduatKarsilastirma(
        oranlar=[],
        enflasyon=32.0,
        en_iyi_vade="TL 6 ay",
        en_iyi_net=34.0,
        en_iyi_reel=reel,
        eur_mevduat_net=2.0,
        tl_mevduat_kazanir=True,
        ozet="test",
        profil_vade="TL 6 ay",
        profil_vade_net=33.0,
        profil_vade_reel=reel,
        profil_vade_eur_tahmini=1.0,
    )


class TutarlilikTest(unittest.TestCase):
    @patch("allocation_engine.rejim_kararli_uygula")
    @patch("allocation_engine.mevduat_analizi")
    def test_rejim_disinda_tl_sinirlanir(self, mock_mev, mock_rejim):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        mock_rejim.return_value = RejimSonucu(
            rejim="NOTR", etiket="Nötr", aciklama="", guven=0.6, adimlar=[]
        )
        snap = _snap(rejim="NOTR")
        profil = YatirimProfili(risk="orta", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        self.assertTrue(tahsis.tl_rejim_sinirlandi)
        self.assertLessEqual(
            tahsis.agirliklar["tl_deposit"],
            config.TL_REJIM_DISI_MAX_ORAN + 0.001,
        )

    @patch("allocation_engine.rejim_kararli_uygula")
    @patch("allocation_engine.mevduat_analizi")
    def test_rejim_disinda_guclu_alim_yok(self, mock_mev, mock_rejim):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        mock_rejim.return_value = RejimSonucu(
            rejim="BELIRSIZ", etiket="Belirsiz", aciklama="", guven=0.4, adimlar=[]
        )
        snap = _snap()
        profil = YatirimProfili(risk="orta", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        rapor = danisman_raporu_olustur(snap, tahsis, profil, mevduat=_pozitif_mevduat())
        tl = next(v for v in rapor.varliklar if v.anahtar == "tl_deposit")
        self.assertNotIn(tl.sinyal, ("GUCLU_AL",))

    @patch("allocation_engine.mevduat_analizi")
    def test_altin_momentum_sinirlanir(self, mock_mev):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        snap = _snap(altin_3m=-12.0)
        tahsis = tahsis_hesapla(snap, YatirimProfili(risk="orta", vade="orta"))
        self.assertLessEqual(
            tahsis.agirliklar["gold"],
            config.ALTIN_MOMENTUM_MAX_ORAN + 0.001,
        )
        self.assertLessEqual(
            tahsis.skorlar["gold"],
            config.ALTIN_MOMENTUM_SKOR_TAVAN + 0.1,
        )

    @patch("allocation_engine.mevduat_analizi")
    def test_cds_stres_tam_tahsis_yeniden_hesaplar(self, mock_mev):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        snap = _snap(cds=240.0)
        profil = YatirimProfili(risk="orta", vade="kisa_6")
        tahsis = tahsis_hesapla(snap, profil)
        mevcut_tl = tahsis.agirliklar.get("tl_deposit", 0)
        satir = _cds_stresi(snap, tahsis, 181)
        stres_tl = float(satir.tablo_satirlar[3][2].strip("%")) / 100.0
        self.assertIn("yeniden hesaplandı", satir.ozet)
        self.assertIn("Tavan bağlayıcı", satir.tablo_satirlar[2][0])
        if mevcut_tl > 0.05:
            self.assertLessEqual(stres_tl, mevcut_tl + 0.001)

    @patch("allocation_engine.mevduat_analizi")
    def test_kur_soku_profil_vadesi(self, mock_mev):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        snap = _snap()
        profil = YatirimProfili(risk="dusuk", vade="kisa_3")
        tahsis = tahsis_hesapla(snap, profil)
        satir_92 = _kur_soku(snap, tahsis, 92)
        satir_181 = _kur_soku(snap, tahsis, 181)
        be_92 = float(satir_92.tablo_satirlar[2][1])
        be_181 = float(satir_181.tablo_satirlar[2][1])
        self.assertNotAlmostEqual(be_92, be_181, places=1)
        self.assertEqual(satir_92.tablo_satirlar[0][1], "92")

    def test_orta_risk_gumus_tavan(self):
        from investor_profile import profil_sinirlari

        _, max_a, _, _ = profil_sinirlari(YatirimProfili(risk="orta", vade="orta"))
        self.assertLessEqual(max_a["silver"], 0.08)

    @patch("allocation_engine.rejim_kararli_uygula")
    @patch("allocation_engine.mevduat_analizi")
    def test_dusuk_risk_kisa3_tl_dusuk_kisa(self, mock_mev, mock_rejim):
        """Düşük risk: kısa vadeli reel pozitif olsa bile TL, uzun vade negatifle aynı bandda."""
        mock_mev.side_effect = lambda **kw: (
            _pozitif_mevduat(6.5) if "3 ay" in str(kw.get("profil_vade", "")) else _negatif_mevduat(-2.7)
        )
        mock_rejim.return_value = RejimSonucu(
            rejim="BELIRSIZ", etiket="Belirsiz", aciklama="", guven=0.4, adimlar=[]
        )
        snap = _snap()
        t_k3 = tahsis_hesapla(snap, YatirimProfili(risk="dusuk", vade="kisa_3"))
        t_k12 = tahsis_hesapla(snap, YatirimProfili(risk="dusuk", vade="kisa"))
        self.assertLessEqual(t_k3.agirliklar["tl_deposit"], config.TL_DUSUK_RISK_MAX_ORAN + 0.001)
        self.assertLessEqual(t_k12.agirliklar["tl_deposit"], config.TL_REEL_COK_NEGATIF_MAX_ORAN + 0.001)
        self.assertLessEqual(
            abs(t_k3.agirliklar["tl_deposit"] - t_k12.agirliklar["tl_deposit"]),
            0.04,
            "Düşük riskte vade farkı TL'yi 21↔2 bandına itmemeli",
        )


def _negatif_mevduat(reel: float = -2.7) -> MevduatKarsilastirma:
    return MevduatKarsilastirma(
        oranlar=[],
        enflasyon=32.0,
        en_iyi_vade="TL 6 ay",
        en_iyi_net=30.0,
        en_iyi_reel=reel,
        eur_mevduat_net=2.0,
        tl_mevduat_kazanir=False,
        ozet="test",
        profil_vade="TL 6 ay",
        profil_vade_net=29.0,
        profil_vade_reel=reel,
        profil_vade_eur_tahmini=-1.0,
    )


if __name__ == "__main__":
    unittest.main()
