# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from investor_profile import YatirimProfili
from tefas_data import FonPerformans, TefasTaramaSonuc
from tefas_skor import fonlari_skorla, kisa_vade_tefas_uygun, top_oneri
from varliklarim import VarlikPortfoy, VarlikPozisyon, VarlikStore


class KisaVadeTefasTest(unittest.TestCase):
    def test_yak_hisse_yogun_elenir(self):
        yak = FonPerformans(
            kod="YAK",
            ad="YAPI KREDİ KARMA",
            kisa_ad="Karma",
            kategori="borclanma",
            kategori_etiket="Borçlanma",
            para_birimi="TL",
            para_etiket="TL",
            fiyat=10.0,
            getiri_3a=8.0,
            hisse_pct=30.0,
            dagilim_ozet="Hisse %30 · Bono %55",
        )
        self.assertFalse(kisa_vade_tefas_uygun(yak))

    def test_pp_gecer(self):
        pp = FonPerformans(
            kod="YPT",
            ad="YAPI KREDİ PP",
            kisa_ad="PP",
            kategori="para_piyasasi",
            kategori_etiket="PP",
            para_birimi="TL",
            para_etiket="TL",
            fiyat=1.7,
            getiri_3a=5.0,
            hisse_pct=0.0,
        )
        self.assertTrue(kisa_vade_tefas_uygun(pp))

    def test_top_oneri_kisa_vade_yak_yok(self):
        pp = FonPerformans(
            kod="YPT", ad="pp", kisa_ad="PP", kategori="para_piyasasi",
            kategori_etiket="PP", para_birimi="TL", para_etiket="TL",
            fiyat=1.7, getiri_1a=4.0, getiri_3a=5.0, oneri="GUCLU", skor=20.0,
        )
        yak = FonPerformans(
            kod="YAK", ad="yak", kisa_ad="Karma", kategori="borclanma",
            kategori_etiket="Bor", para_birimi="TL", para_etiket="TL",
            fiyat=10.0, getiri_1a=6.0, getiri_3a=8.0, hisse_pct=30.0,
            oneri="GUCLU", skor=22.0,
        )
        sonuc = TefasTaramaSonuc(fonlar=[yak, pp])
        aday = top_oneri(
            sonuc, n=2,
            kategoriler=("para_piyasasi", "borclanma", "katilim"),
            kisa_vade=True,
        )
        self.assertEqual(len(aday), 1)
        self.assertEqual(aday[0].kod, "YPT")


class SiyasiTabanTest(unittest.TestCase):
    def test_referans_taban_guncelden_farkli(self):
        import siyasi_esik as se

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.db")
            with patch.object(se, "CACHE_DB", db):
                es = se.esikler()
                self.assertEqual(es["taban_kaynak"], "referans")
                self.assertLess(es["taban"], se.config.SIYASI_RISK_TABAN_VARSAYILAN)

    def test_min_taban_bugunden_dusuk(self):
        import siyasi_esik as se

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.db")
            with patch.object(se, "CACHE_DB", db):
                conn = sqlite3.connect(db)
                conn.execute(
                    "CREATE TABLE siyasi_baseline "
                    "(gun TEXT PRIMARY KEY, sayi INTEGER NOT NULL, ts REAL NOT NULL)"
                )
                for i, (gun, sayi) in enumerate(
                    [
                        ("2026-07-01", 52),
                        ("2026-07-02", 54),
                        ("2026-07-03", 53),
                        ("2026-07-04", 55),
                        ("2026-07-05", 52),
                        ("2026-07-06", 54),
                        ("2026-07-07", 53),
                    ]
                ):
                    conn.execute(
                        "INSERT INTO siyasi_baseline VALUES (?, ?, ?)",
                        (gun, sayi, float(i)),
                    )
                conn.commit()
                conn.close()

                es = se.esikler()
                self.assertEqual(es["taban_kaynak"], "14g_min")
                self.assertEqual(es["taban"], 52)
                metin = se.esik_metni(guncel=54)
                self.assertIn("14g min", metin)


class BistSepetTest(unittest.TestCase):
    def _hisse(self, sembol, uygun="UYGUN", skor=90.0):
        h = MagicMock()
        h.piyasa = "BIST"
        h.sembol = sembol
        h.ad = sembol
        h.alim_uygun = uygun
        h.skor = skor
        h.bilesik_skor = skor
        return h

    def test_skor_en_yuksek_secilir(self):
        from bist_sepet import bist_sepet_sec

        tarama = MagicMock()
        tarama.hisseler = [
            self._hisse("EKGYO.IS", skor=95),
            self._hisse("DOAS.IS", skor=80),
            self._hisse("SAHOL.IS", skor=75),
        ]
        store = VarlikStore(
            aktif_id="p1",
            portfoyler=[
                VarlikPortfoy(
                    id="p1",
                    ad="Test",
                    pozisyonlar=[
                        VarlikPozisyon(id="1", tur="hisse", sembol="DOAS", miktar=100),
                        VarlikPozisyon(id="2", tur="hisse", sembol="SAHOL", miktar=50),
                    ],
                )
            ],
        )
        profil = YatirimProfili(vade="kisa_6", risk="orta")
        sepet, notlar = bist_sepet_sec(tarama, profil, 0.04, store)
        self.assertEqual(len(sepet), 1)
        self.assertEqual(sepet[0].sembol, "EKGYO.IS")
        self.assertFalse(any("korunur" in n for n in notlar))

    def test_al_hemen_sepete_girer(self):
        from bist_sepet import bist_sepet_sec

        tarama = MagicMock()
        tarama.hisseler = [self._hisse("EKGYO.IS")]
        profil = YatirimProfili(vade="kisa_6", risk="orta")
        sepet, _ = bist_sepet_sec(tarama, profil, 0.04, None)
        self.assertEqual(len(sepet), 1)
        self.assertEqual(sepet[0].sembol, "EKGYO.IS")

    def test_al_degilse_sepete_girmez(self):
        from bist_sepet import bist_sepet_sec

        tarama = MagicMock()
        tarama.hisseler = [self._hisse("EKGYO.IS", uygun="IZLE")]
        profil = YatirimProfili(vade="kisa_6", risk="orta")
        sepet, _ = bist_sepet_sec(tarama, profil, 0.04, None)
        self.assertEqual(sepet, [])


if __name__ == "__main__":
    unittest.main()
