# -*- coding: utf-8 -*-
import unittest

from advice_engine import danisman_raporu_olustur
from allocation_engine import tahsis_hesapla
from audit_engine import denetim_calistir
from decision_engine import PiyasaVerisi
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot


def _snap(enf_kaynak: str, enf: float = 32.11):
    return MacroSnapshot(
        veri=PiyasaVerisi(
            eur_try=53.5,
            usd_try=57.8,
            tcmb_politika_faizi=37.0,
            cds_5y_bp=240.0,
            siyasi_risk_makale_sayisi=10,
        ),
        enflasyon_tr_yillik=enf,
        vix=18.0,
        kaynak_haritasi={"enflasyon": enf_kaynak, "cds": "Investing"},
        veri_kaynak="canli",
    )


class AuditEnflasyonTest(unittest.TestCase):
    def test_resmi_tuik_uyari_vermez(self):
        snap = _snap(
            "TÜİK/resmi — TÜİK Haziran 2026 yıllık TÜFE — resmi bülten (2026-6)",
        )
        profil = YatirimProfili(risk="orta", vade="kisa_3")
        tahsis = tahsis_hesapla(snap, profil)
        rapor = danisman_raporu_olustur(snap, tahsis, profil)
        denetim = denetim_calistir(
            snap, tahsis, rapor.varliklar, mevduat=None, oncelik=rapor.oncelik_sirasi,
        )
        basliklar = [b.baslik for b in denetim.bulgular]
        self.assertNotIn("Enflasyon yıllık/gecikmeli kaynaktan (TÜİK değil)", basliklar)

    def test_fred_uyari_verir(self):
        snap = _snap("World Bank yıllık enflasyon (gecikmeli)")
        profil = YatirimProfili()
        tahsis = tahsis_hesapla(snap, profil)
        rapor = danisman_raporu_olustur(snap, tahsis, profil)
        denetim = denetim_calistir(snap, tahsis, rapor.varliklar)
        basliklar = [b.baslik for b in denetim.bulgular]
        self.assertIn("Enflasyon yıllık/gecikmeli kaynaktan (TÜİK değil)", basliklar)


if __name__ == "__main__":
    unittest.main()
