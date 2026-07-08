# -*- coding: utf-8 -*-
"""Rapor eksikleri — TMSF, girdi doğrulama, TL minimal reel pozitif."""
import unittest

from decision_engine import PiyasaVerisi
from girdi_dogrulama import girdi_rapor_uyarilari
from macro_data import MacroSnapshot
from rates_tr import tmsf_uyari_satirlari
from tl_durum import tl_durum_olustur
from allocation_engine import tahsis_hesapla
from investor_profile import YatirimProfili
from rates_tr import MevduatKarsilastirma


def _snap(cds=265.0):
    veri = PiyasaVerisi(
        eur_try=53.62,
        usd_try=32.0,
        fed_faizi=4.0,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=0.40,
        cds_5y_bp=cds,
        rezerv_artiyor=True,
        siyasi_risk_makale_sayisi=10,
    )
    return MacroSnapshot(veri=veri, vix=18.0, enflasyon_tr_yillik=35.0, eur_usd=1.08)


class RaporEksikleriTest(unittest.TestCase):
    def test_tmsf_limit_ustu(self):
        uyar = tmsf_uyari_satirlari(1_200_000)
        self.assertTrue(any("aşılıyor" in u for u in uyar))

    def test_tmsf_limit_alti_bilgi(self):
        uyar = tmsf_uyari_satirlari(32_000)
        self.assertTrue(any("TMSF bilgi" in u for u in uyar))

    def test_girdi_rapor_rejim_donduruldu(self):
        snap = _snap()
        from girdi_dogrulama import GirdiDogrulamaSonucu, GostergeSonuc

        snap.girdi_dogrulama = GirdiDogrulamaSonucu(
            rejim_donduruldu=True,
            onay_bekleyen=["cds"],
            gostergeler={
                "cds": GostergeSonuc(
                    anahtar="cds",
                    deger=300.0,
                    durum="ONAY_BEKLIYOR",
                    uyari="Girdi sıçraması — cds 222.00 → 300.00",
                    onceki=222.0,
                    rejim_icin_deger=222.0,
                )
            },
        )
        snap.rejim_donduruldu = True
        satirlar = girdi_rapor_uyarilari(snap)
        self.assertTrue(any("donduruldu" in s.lower() for s in satirlar))

    def test_tl_minimal_reel_pozitif(self):
        snap = _snap()
        profil = YatirimProfili(risk="orta", vade="uzun")
        tahsis = tahsis_hesapla(snap, profil)
        mev = MevduatKarsilastirma(
            profil_vade_reel=2.5,
            profil_vade_net=37.5,
            profil_vade="TL 1 yıl",
            profil_vade_eur_tahmini=0.5,
        )
        durum = tl_durum_olustur(snap, tahsis, mev)
        if tahsis.agirliklar.get("tl_deposit", 0) * 100 < 5:
            metin = (durum.baslik + " " + durum.oneri_cumlesi).lower()
            self.assertTrue(
                "sınırlayan" in metin or "reel pozitif" in metin or "faiz matematiği" in metin
            )


if __name__ == "__main__":
    unittest.main()
