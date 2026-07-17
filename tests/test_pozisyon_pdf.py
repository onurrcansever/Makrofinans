# -*- coding: utf-8 -*-
import unittest

from report_pdf import pozisyonlar_pdf_olustur


class PozisyonPdfTest(unittest.TestCase):
    def test_pozisyonlar_pdf_uretir(self):
        satirlar = [
            {
                "id": "1",
                "arac": "Akbank",
                "sembol": "AKBNK.IS",
                "miktar": "100",
                "alis": "12.50",
                "guncel": "24.00",
                "maliyet": "1.250 TL",
                "deger": "2.400 TL",
                "kz": "+1.150 (+92.0%)",
                "sinyal": "İZLE",
                "oneri": "Çıkış değerlendir",
                "oneri_aciklama": "Çıkış değerlendirin — K/Z +92.0%",
                "ekle": "—",
                "stop": "22.00 TL",
                "skor": 55,
                "getiriler": {"1A (TL)": "+5,2%"},
                "plan": "🟡 Çıkış değerlendir · İZLE",
                "uyari": "**Akbank** — K/Z **+92.0%**",
            }
        ]
        pdf = pozisyonlar_pdf_olustur(
            portfoy_ad="Test Portföy",
            gosterim_pb="TL",
            pozisyonlar=satirlar,
            ozet={"toplam": 2400, "maliyet": 1250, "kz": 1150, "kz_pct": 92.0},
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)

    def test_tek_pozisyon_filtresi(self):
        satirlar = [
            {"id": "a", "arac": "A", "sembol": "A", "kz": "0", "sinyal": "—", "oneri": "Elde tut"},
            {"id": "b", "arac": "B", "sembol": "B", "kz": "0", "sinyal": "—", "oneri": "Elde tut"},
        ]
        pdf = pozisyonlar_pdf_olustur(
            portfoy_ad="P",
            gosterim_pb="EUR",
            pozisyonlar=satirlar,
            ozet={"toplam": 100, "maliyet": 100, "kz": 0, "kz_pct": 0},
            pozisyon_id="b",
        )
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
