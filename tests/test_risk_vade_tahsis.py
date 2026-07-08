# -*- coding: utf-8 -*-
"""Risk profili × vade tutarlılığı — 0–12 ay yüksek risk tahsis farkı."""
import unittest
from unittest.mock import MagicMock, patch

from allocation_engine import tahsis_hesapla
from audit_engine import denetim_calistir
from birlesik_oneri import AracDagilimSatir
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili, profil_degerlendirme
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma
from regime import RejimSonucu
from scenario_analysis import _kur_soku, senaryo_analizi_uret


def _snap(cds: float = 240.0):
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
        altin_3m_degisim=5.0,
        bist100_3m_degisim=8.0,
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


class RiskVadeTahsisTest(unittest.TestCase):
    @patch("allocation_engine.rejim_tespit_v2")
    @patch("allocation_engine.mevduat_analizi")
    def test_yuksek_risk_kisa_bist_orta_riskten_fazla(self, mock_mev, mock_rejim):
        mock_mev.return_value = _pozitif_mevduat(2.5)
        mock_rejim.return_value = RejimSonucu(
            rejim="TL_FIRSAT", etiket="TL Fırsat", aciklama="", guven=0.7, adimlar=[]
        )
        snap = _snap()
        orta = tahsis_hesapla(snap, YatirimProfili(risk="orta", vade="kisa"))
        yuksek = tahsis_hesapla(snap, YatirimProfili(risk="yuksek", vade="kisa"))
        self.assertGreater(
            yuksek.agirliklar["bist"],
            orta.agirliklar["bist"],
            "yüksek risk 0–12 ay BIST payını artırmalı",
        )

    def test_profil_notu_kisa_vade_artirilabilir_demez(self):
        notlar = profil_degerlendirme(YatirimProfili(risk="yuksek", vade="kisa"), "TL_FIRSAT")
        birlesik = " ".join(notlar)
        self.assertNotIn("artırılabilir (4 kapı", birlesik)
        self.assertIn("0–12 ay", birlesik)

    @patch("allocation_engine.rejim_tespit_v2")
    @patch("allocation_engine.mevduat_analizi")
    def test_kisa_vade_tl_uyari_bilgi_seviyesinde(self, mock_mev, mock_rejim):
        from advice_engine import danisman_raporu_olustur

        mock_mev.return_value = _pozitif_mevduat(2.5)
        mock_rejim.return_value = RejimSonucu(
            rejim="TL_FIRSAT", etiket="TL Fırsat", aciklama="", guven=0.7, adimlar=[]
        )
        snap = _snap()
        profil = YatirimProfili(risk="yuksek", vade="kisa")
        tahsis = tahsis_hesapla(snap, profil)
        rapor = danisman_raporu_olustur(snap, tahsis, profil, mevduat=mock_mev.return_value)
        basliklar = [b.baslik for b in rapor.denetim.bulgular]
        self.assertNotIn("TL fırsat rejimi ama düşük tahsis", basliklar)

    def test_kur_soku_sepet_etfleri(self):
        snap = _snap()
        profil = YatirimProfili(risk="yuksek", vade="kisa")
        tahsis = tahsis_hesapla(snap, profil, ham_rejim=True)
        birlesik = MagicMock()
        birlesik.arac_dagilim = [
            AracDagilimSatir(
                ust_kategori="ETF (hisse senedi)",
                arac="CSPX.L",
                aciklama="S&P 500",
                portfoy_pct=10.0,
                kategori_ici_pct=55.0,
                tutar=3000.0,
                para="EUR",
            ),
            AracDagilimSatir(
                ust_kategori="ETF (hisse senedi)",
                arac="VUAA.L",
                aciklama="MSCI World",
                portfoy_pct=6.0,
                kategori_ici_pct=45.0,
                tutar=1800.0,
                para="EUR",
            ),
        ]
        satir = _kur_soku(snap, tahsis, 181, birlesik_oneri=birlesik)
        self.assertIn("CSPX", satir.ozet)
        self.assertIn("VUAA", satir.ozet)


if __name__ == "__main__":
    unittest.main()
