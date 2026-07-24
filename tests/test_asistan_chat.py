# -*- coding: utf-8 -*-
"""asistan_chat — baglam + mock çok turlu yanıt + grounding."""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch

from asistan_chat import (
    _system_prompt,
    _temkinli_rejim,
    _trim_history,
    asistan_yanit,
    baglam_sembol_allowlist,
    kaynak_dipnotu,
    odak_sembol_bul,
    sistem_baglam_ozeti,
    ticker_grounding,
)


@dataclass
class _FakeSnap:
    vix: float = 18.0
    vix_1g_degisim: float = -2.0
    bist100: float = 10000.0
    bist100_1g_degisim: float = 0.5
    altin_usd_oz: float = 2300.0
    altin_1g_degisim: float = 0.2
    enflasyon_tr_yillik: float = 35.0
    bist_vol_30g: float = 20.0
    eur_try_1g_degisim: float = 0.1
    veri: object = field(default_factory=lambda: type("V", (), {"eur_try": 36.5, "cds_5y_bp": 280})())


@dataclass
class _FakeRejim:
    etiket: str = "Nötr"
    rejim: str = "NOTR"


@dataclass
class _FakeTahsis:
    rejim: _FakeRejim = field(default_factory=_FakeRejim)
    agirliklar: dict = field(default_factory=lambda: {"equity_tr": 0.2, "gold": 0.15, "tl_deposit": 0.3})


@dataclass
class _FakeHisse:
    sembol: str = "THYAO.IS"
    ad: str = "THY"
    piyasa: str = "BIST"
    signal_v2_decision: str = "AL"
    signal_v2_score: float = 72.0
    signal_v2_al_price: float = 280.0
    degisim_1g: float = 1.2
    signal_v2_why: str = "Momentum"
    fiyat: float = 285.0
    rsi: float = 53.0
    sma20: float = 290.0
    sma50: float = 275.0
    sma200: float = 260.0
    signal_v2_al_method: str = "pullback"
    signal_v2_spot_near: bool = False
    signal_v2_ichimoku: dict = field(
        default_factory=lambda: {"buy_zone": False, "note": "bulut üstü TK zayıf"}
    )
    signal_v2_ready_note: bool = False
    signal_v2_small_size: bool = False
    signal_v2_regime: str = "TRENDING_UP"
    signal_v2_regime_detail: str = ""


@dataclass
class _FakeEndeks:
    ad: str = "BIST 100"
    sembol: str = "XU100.IS"
    fiyat: float = 10000.0
    degisim_1g: float = 0.5
    degisim_1ay: float = 2.0
    aksiyon_etiket: str = "Koru"
    gerekce: str = "Nötr"


@dataclass
class _FakeTarama:
    hisseler: List = field(default_factory=lambda: [_FakeHisse()])
    endeksler: List = field(default_factory=lambda: [_FakeEndeks()])


@dataclass
class _FakeFon:
    kod: str = "AFT"
    ad: str = "Örnek Fon"
    kisa_ad: str = "Örnek"
    kategori: str = "borclanma"
    skor: float = 70.0
    oneri: str = "AL"


@dataclass
class _FakeTefas:
    fonlar: List = field(default_factory=lambda: [_FakeFon()])


class AsistanChatTest(unittest.TestCase):
    def test_baglam_anahtarlar(self):
        b = sistem_baglam_ozeti(
            snap=_FakeSnap(),
            tahsis=_FakeTahsis(),
            tarama=_FakeTarama(),
            tefas_ham=_FakeTefas(),
        )
        for k in (
            "makro",
            "rejim",
            "rejim_kod",
            "tahsis_agirlik_pct",
            "endeksler",
            "al_adaylari",
            "izle_takip",
            "danisman",
            "portfoy",
            "tefas_ust",
            "nakit_plani",
            "temkinli_rejim",
        ):
            self.assertIn(k, b)
        self.assertEqual(b["al_adet"], 1)
        self.assertEqual(b["al_adaylari"][0]["sembol"], "THYAO.IS")
        self.assertEqual(b["tefas_ust"][0]["kod"], "AFT")
        self.assertIn("equity_tr", b["tahsis_agirlik_pct"])
        self.assertAlmostEqual(b["makro"]["vix"], 18.0)

    def test_system_prompt_kurallar(self):
        b = sistem_baglam_ozeti(snap=_FakeSnap(), tahsis=_FakeTahsis(), tarama=_FakeTarama())
        p = _system_prompt(b)
        self.assertIn("kesinlikle al/sat", p.lower())
        self.assertIn("VERİ", p)
        self.assertIn("THYAO.IS", p)
        self.assertIn("uydurma", p.lower())

    def test_baglam_sikistir_kisa(self):
        from asistan_chat import baglam_sikistir

        b = sistem_baglam_ozeti(snap=_FakeSnap(), tahsis=_FakeTahsis(), tarama=_FakeTarama())
        k = baglam_sikistir(b)
        self.assertLessEqual(len(k.get("al_adaylari") or []), 5)
        # kompakt endeks: neden kısa tutulur
        if k.get("endeksler"):
            self.assertIn("oneri", k["endeksler"][0])

    def test_429_mesaj(self):
        b = sistem_baglam_ozeti()

        def _boom(*_a, **_kw):
            raise RuntimeError("LLM HTTP 429 daily_quota")

        with patch("asistan_chat.call_chat", side_effect=_boom):
            metin, meta = asistan_yanit(b, [], "test")
        self.assertIn("429", meta.get("hata") or "")
        self.assertIn("kota", metin.lower())

    def test_rejim_kilidi_prompt(self):
        tahsis = _FakeTahsis()
        tahsis.rejim = _FakeRejim(etiket="Kriz savunma", rejim="KRIZ")
        b = sistem_baglam_ozeti(snap=_FakeSnap(), tahsis=tahsis, tarama=_FakeTarama())
        self.assertTrue(b["temkinli_rejim"])
        p = _system_prompt(b)
        self.assertIn("REJİM KİLİDİ", p)

    def test_odak_sembol(self):
        tarama = _FakeTarama()
        odak = odak_sembol_bul("THYAO nasıl?", tarama=tarama)
        self.assertIsNotNone(odak)
        self.assertEqual(odak["sembol"], "THYAO.IS")
        self.assertEqual(odak["karar"], "AL")
        self.assertIn("teknik", odak)
        self.assertIn("aksiyon_okuma", odak["teknik"])
        self.assertFalse(odak["teknik"]["ichimoku_buy_zone"])
        b = sistem_baglam_ozeti(tarama=tarama, user_msg="THYAO neden AL?")
        self.assertEqual(b["odak_sembol"]["sembol"], "THYAO.IS")
        kompakt = __import__("asistan_chat", fromlist=["baglam_sikistir"]).baglam_sikistir(b)
        self.assertIsNotNone(kompakt["odak_sembol"].get("teknik"))
        self.assertIn("Ichimoku", _system_prompt(b))
        self.assertIn("RSI", str(kompakt["odak_sembol"]["teknik"]))

    def test_kaynak_dipnotu(self):
        b = sistem_baglam_ozeti(snap=_FakeSnap(), tahsis=_FakeTahsis(), tarama=_FakeTarama())
        d = kaynak_dipnotu(b)
        self.assertIn("Kaynak:", d)
        self.assertIn("VIX", d)
        self.assertIn("AL", d)

    def test_ticker_grounding(self):
        b = sistem_baglam_ozeti(tarama=_FakeTarama())
        allow = baglam_sembol_allowlist(b)
        self.assertIn("THYAO", allow)
        _, bad = ticker_grounding("THYAO iyi; XYZABC alınabilir.", allow)
        self.assertIn("XYZABC", bad)
        self.assertNotIn("THYAO", bad)

    def test_trim_history(self):
        hist = [{"role": "user", "content": f"s{i}"} for i in range(20)]
        t = _trim_history(hist, max_turns=3)
        self.assertEqual(len(t), 6)
        self.assertEqual(t[-1]["content"], "s19")

    def test_yanit_mock_dipnot(self):
        b = sistem_baglam_ozeti(snap=_FakeSnap(), tahsis=_FakeTahsis(), tarama=_FakeTarama())
        metin, meta = asistan_yanit(
            b,
            [],
            "Hangi hisseler önde?",
            _call_fn=lambda blob: "THYAO öncelikli AL adayı olarak görünüyor.",
        )
        self.assertIn("THYAO", metin)
        self.assertIn("Kaynak:", metin)
        self.assertFalse(meta.get("hata"))

    def test_yanit_grounding_uyari(self):
        b = sistem_baglam_ozeti(tarama=_FakeTarama())
        metin, meta = asistan_yanit(
            b,
            [],
            "Ne alayım?",
            _call_fn=lambda blob: "ZZZZTOP alınabilir.",
        )
        self.assertIn("ZZZZTOP", meta.get("grounding_uyari") or [])
        self.assertIn("veride olmayan", metin.lower())

    def test_yanit_history_passed_to_mock(self):
        b = sistem_baglam_ozeti()
        captured = []

        def _fn(blob: str) -> str:
            captured.append(blob)
            return "Tamam."

        asistan_yanit(
            b,
            [{"role": "user", "content": "Merhaba"}, {"role": "assistant", "content": "Selam"}],
            "Peki VIX?",
            _call_fn=_fn,
        )
        self.assertEqual(len(captured), 1)
        self.assertIn("Merhaba", captured[0])
        self.assertIn("Peki VIX?", captured[0])
        self.assertIn("[system]", captured[0])

    def test_no_key(self):
        b = sistem_baglam_ozeti()
        with patch("asistan_chat.provider_ready", return_value=False):
            metin, meta = asistan_yanit(b, [], "test")
        self.assertEqual(meta.get("hata"), "no_key")
        self.assertIn("Yanıt", metin)

    def test_temkinli_vix(self):
        snap = _FakeSnap(vix=32.0)
        b = sistem_baglam_ozeti(snap=snap, tahsis=_FakeTahsis())
        self.assertTrue(_temkinli_rejim(b))


if __name__ == "__main__":
    unittest.main()
