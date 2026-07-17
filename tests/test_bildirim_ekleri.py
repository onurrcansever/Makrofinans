# -*- coding: utf-8 -*-
"""Bildirim ekleri — cache-only temel/AI/portföy (API yok)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import bildirim_ekleri as be
import llm_aciklama as llm
import portfoy_yorum as py
import temel_veri as tv
from signal_alerts import alarm_metni_olustur
from ozet_bildirim import ozet_metni_olustur


def _hisse(**kw):
    base = dict(
        sembol="HALKB.IS",
        ad="Halkbank",
        skor=80,
        rsi=42.0,
        sinyal="BEKLE",
        alim_uygun="UYGUN",
        alim_uygun_not="Skor 80 (sınıf %85)",
        piyasa="BIST",
        varlik_turu="hisse",
        fiyat=1.0,
        signal_v2_decision="AL",
        signal_v2_score=80.0,
        signal_v2_percentile=85.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class BildirimEkleriTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tv = tv.STATE_PATH
        self._llm = llm.STATE_PATH
        self._py = py.STATE_PATH
        tv.STATE_PATH = os.path.join(self._td.name, "temel.json")
        llm.STATE_PATH = os.path.join(self._td.name, "llm.json")
        py.STATE_PATH = os.path.join(self._td.name, "py.json")

    def tearDown(self):
        tv.STATE_PATH = self._tv
        llm.STATE_PATH = self._llm
        py.STATE_PATH = self._py
        self._td.cleanup()

    def _yaz_temel(self, sembol="HALKB.IS"):
        tv.kaydet_cache({
            sembol: {
                "trailingPE": 5.2,
                "recommendationKey": "strong_buy",
                "numberOfAnalystOpinions": 8,
                "targetMeanPrice": 11.8,
                "currentPrice": 10.0,
                "guncelleme": date.today().isoformat(),
            },
        })

    def _yaz_llm(self, sembol="HALKB.IS", karar="AL", skor=80):
        key = llm.cache_anahtar(sembol, karar, skor)
        llm.kaydet_cache({
            key: {
                "metin": (
                    "Teknik momentum güçlü, değerleme cazip görünüyor. "
                    "Analist konsensüsü destekliyor. Üçüncü cümle olmamalı."
                ),
                "guncelleme": date.today().isoformat(),
                "sembol": sembol.upper(),
                "karar": karar,
                "skor": skor,
            },
        })

    def test_cache_var_alarm_ai_icerir(self):
        self._yaz_temel()
        self._yaz_llm()
        h = _hisse()
        tahsis = SimpleNamespace(rejim=SimpleNamespace(etiket="Test"))
        profil = SimpleNamespace(ozet=lambda: "Orta risk")
        metin = alarm_metni_olustur([("AL", h.sembol, h)], tahsis, profil)
        self.assertIn("📊 F/K: 5.2x", metin)
        self.assertIn("Analist: 8→ Güçlü Al", metin)
        self.assertIn("Hedef: +18%", metin)
        self.assertIn("💬 Teknik momentum güçlü", metin)
        # Tek cümle — ikinci cümle kesilmeli
        self.assertNotIn("Üçüncü cümle", metin)
        # Ek satırlar ≤200
        for line in metin.splitlines():
            if line.strip().startswith("📊") or "💬" in line:
                self.assertLessEqual(len(line.strip()), be.MAX_EK_KARAKTER + 2)

    def test_cache_yok_alarm_sessiz(self):
        h = _hisse()
        tahsis = SimpleNamespace(rejim=SimpleNamespace(etiket="Test"))
        profil = SimpleNamespace(ozet=lambda: "Orta risk")
        metin = alarm_metni_olustur([("AL", h.sembol, h)], tahsis, profil)
        self.assertIn("YATIRIM SİNYALİ", metin)
        self.assertIn("HALKB.IS", metin)
        self.assertNotIn("📊", metin)
        self.assertNotIn("💬", metin)

    def test_etf_temel_yok_ai_varsa_goster(self):
        self._yaz_llm("CSPX.L", "GÜÇLÜ AL", 84)
        # Temel cache olsa bile ETF satırı yok
        tv.kaydet_cache({
            "CSPX.L": {
                "trailingPE": 22.0,
                "quoteType": "ETF",
                "guncelleme": date.today().isoformat(),
            },
        })
        h = _hisse(
            sembol="CSPX.L", ad="CSPX", piyasa="ETF", varlik_turu="etf",
            signal_v2_decision="GÜÇLÜ AL", signal_v2_score=84, skor=84,
        )
        ek = be.sinyal_ek_satirlari(h)
        self.assertFalse(any("📊" in x for x in ek))
        self.assertTrue(any("💬" in x for x in ek))

    def test_portfoy_durum_cache_yorum(self):
        py.kaydet_cache({
            "abc123": {
                "metin": (
                    "Portföyünüzün %38'i ABD teknoloji sektöründe yoğunlaşmış. "
                    "Temkinli izleme destekleniyor."
                ),
                "guncelleme": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "ozet": {
                    "toplam_pozisyon": 12,
                    "azalt_agirlik_pct": 25.3,
                    "ortalama_skor": 54,
                    "portfoy_kz_pct": -8.2,
                    "en_buyuk_sektor": "ABD teknoloji %38",
                },
            },
        })
        with patch("bildirim_ekleri.yukle_store", create=True):
            pass
        # portfoy_ozet başarısız → cache ozet kullan
        with patch.object(be, "_portfoy_yorum_cache_son", wraps=be._portfoy_yorum_cache_son):
            with patch("varliklarim.yukle_store", side_effect=RuntimeError("yok")):
                satirlar = be.portfoy_durum_satirlari()
        metin = "\n".join(satirlar)
        self.assertIn("PORTFÖY DURUMU", metin)
        self.assertIn("54/100", metin)
        self.assertIn("💬", metin)
        self.assertIn("teknoloji", metin.lower())
        for line in satirlar:
            if line.startswith("💬"):
                self.assertLessEqual(len(line), be.MAX_EK_KARAKTER)

    def test_portfoy_cache_yok_yorum_atlaniyor(self):
        # Boş cache; ozet hesap da boş portföy → []
        with patch("varliklarim.yukle_store") as mock_store:
            mock_store.return_value = SimpleNamespace(
                aktif=lambda: SimpleNamespace(pozisyonlar=[]),
            )
            satirlar = be.portfoy_durum_satirlari()
        self.assertEqual(satirlar, [])

    def test_ozet_metni_portfoy_blogu(self):
        py.kaydet_cache({
            "x": {
                "metin": "Konsantrasyon yüksek. Temkinli duruş uygun.",
                "guncelleme": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "ozet": {
                    "ortalama_skor": 54,
                    "azalt_agirlik_pct": 25.3,
                    "portfoy_kz_pct": -8.2,
                },
            },
        })
        tahsis = SimpleNamespace(
            rejim=SimpleNamespace(etiket="Enflasyon"),
            agirliklar={"eur_cash": 0.5},
            tl_tavan_oran=0.1,
        )
        profil = SimpleNamespace(ozet=lambda: "Orta")
        tarama = SimpleNamespace(hisseler=[])
        with patch(
            "ozet_bildirim._varlik_satirlari",
            return_value=["VARLIKLAR: 100.000 TL", " K/Z: +1.000 TL (+1,0%)"],
        ):
            with patch("varliklarim.yukle_store", side_effect=RuntimeError("x")):
                metin = ozet_metni_olustur(
                    tahsis, profil, tarama, [], False, None, None,
                    snap=SimpleNamespace(),
                )
        self.assertIn("VARLIKLAR:", metin)
        self.assertIn("PORTFÖY DURUMU", metin)
        self.assertIn("💬", metin)


    def test_portfoy_pozisyon_tablo_satirlari(self):
        from varliklarim import VarlikPozisyon, VarlikPortfoy, VarlikStore
        from varlik_fiyat import PozisyonDeger

        h = _hisse(signal_v2_decision="İZLE", signal_v2_score=59.0)
        tarama = SimpleNamespace(hisseler=[h])
        p = VarlikPozisyon(id="1", tur="hisse", sembol="HALKB.IS", miktar=100, maliyet=3500)
        portfoy = VarlikPortfoy(id="a", ad="Ana", pozisyonlar=[p])
        pd_ = PozisyonDeger(
            pozisyon=p, miktar_goster="100", alim_birim=35.0, guncel_birim=32.5,
            maliyet_deger=3500, guncel_deger=3250, kar_zarar=-250, kar_zarar_pct=-7.1,
            para="TL", getiriler={},
        )
        snap = SimpleNamespace(veri=SimpleNamespace(eur_try=35.5, usd_try=35.0))

        with patch("varliklarim.yukle_store") as mock_store, \
             patch("varlik_fiyat.portfoy_degerle") as mock_deger, \
             patch("fiyat_para.tablo_fx_hazirla") as mock_fx, \
             patch("portfoy_yoneticisi.yonetici_pozisyon_kolonlari") as mock_kol, \
             patch.object(be, "_tefas_bildirim_yukle", return_value=(None, None)):
            mock_store.return_value = VarlikStore(portfoyler=[portfoy], aktif_id="a")
            mock_deger.return_value = SimpleNamespace(pozisyonlar=[pd_])
            mock_fx.return_value = (
                SimpleNamespace(eur_try=35.5, usd_try=35.0, gbp_usd=1.34, eur_usd=35 / 35.5),
                None, None, None, None,
            )
            from portfoy_yoneticisi import POZ_COL_ONERI, POZ_COL_SINYAL
            mock_kol.return_value = {
                POZ_COL_SINYAL: "İZLE",
                POZ_COL_ONERI: {"code": "Tut", "label": "Elde tut", "tip": ""},
                "Ekle": "—", "Stop": "30 EUR",
            }
            satirlar = be.portfoy_pozisyon_tablo_satirlari(snap, tarama)

        metin = "\n".join(satirlar)
        self.assertIn("POZİSYONLAR", metin)
        self.assertIn("HALKB", metin.upper())
        self.assertIn("İZLE", metin)
        self.assertIn("Elde tut", metin)
        self.assertIn("-7,1%", metin)

    def test_ozet_metni_pozisyon_tablosu(self):
        py.kaydet_cache({
            "x": {
                "metin": "Konsantrasyon yüksek.",
                "guncelleme": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "ozet": {"ortalama_skor": 63, "azalt_agirlik_pct": 0, "portfoy_kz_pct": -1.1},
            },
        })
        tahsis = SimpleNamespace(
            rejim=SimpleNamespace(etiket="TL mevduat fırsatı"),
            agirliklar={"tl_deposit": 0.4},
            tl_tavan_oran=0.45,
        )
        profil = SimpleNamespace(ozet=lambda: "Orta risk · 0–6 ay")
        tarama = SimpleNamespace(hisseler=[])
        poz_sat = ["📊 POZİSYONLAR (EUR)", "HALKB · İZLE · Elde tut · -7,1%"]
        with patch(
            "ozet_bildirim._varlik_satirlari",
            return_value=["VARLIKLAR: 1.184.101 TL", " K/Z: -13.430 TL (-1,1%)"],
        ), patch(
            "bildirim_ekleri.portfoy_pozisyon_tablo_satirlari", return_value=poz_sat,
        ):
            with patch("varliklarim.yukle_store", side_effect=RuntimeError("x")):
                metin = ozet_metni_olustur(
                    tahsis, profil, tarama, [], False, None, None,
                    snap=SimpleNamespace(),
                )
        self.assertIn("POZİSYONLAR", metin)
        self.assertIn("HALKB", metin)


if __name__ == "__main__":
    unittest.main()
