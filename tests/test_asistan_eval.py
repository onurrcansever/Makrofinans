# -*- coding: utf-8 -*-
"""Asistan eval seti — fixtures/asistan_eval.json."""
from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch

from asistan_chat import _system_prompt, asistan_yanit, sistem_baglam_ozeti

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "asistan_eval.json"
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


def _yukle_senaryolar():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class AsistanEvalTest(unittest.TestCase):
    def _baglam(self, case: dict):
        snap = _FakeSnap()
        if case.get("vix") is not None:
            snap.vix = float(case["vix"])
        tahsis = _FakeTahsis()
        if case.get("rejim_kod"):
            tahsis.rejim = _FakeRejim(
                etiket=str(case.get("rejim_etiket") or case["rejim_kod"]),
                rejim=str(case["rejim_kod"]),
            )
        return sistem_baglam_ozeti(
            snap=snap,
            tahsis=tahsis,
            tarama=_FakeTarama(),
            tefas_ham=_FakeTefas(),
            user_msg=case.get("soru") or "",
        )

    def test_eval_fixture(self):
        cases = _yukle_senaryolar()
        self.assertGreaterEqual(len(cases), 12)
        for case in cases:
            with self.subTest(id=case.get("id")):
                b = self._baglam(case)
                if case.get("temkinli_rejim") is True:
                    self.assertTrue(b.get("temkinli_rejim"))
                if case.get("odak_sembol"):
                    self.assertEqual(
                        (b.get("odak_sembol") or {}).get("sembol"),
                        case["odak_sembol"],
                    )
                if case.get("prompt_icerir"):
                    p = _system_prompt(b)
                    for frag in case["prompt_icerir"]:
                        self.assertIn(frag, p)

                if case.get("no_key"):
                    with patch("asistan_chat.provider_ready", return_value=False):
                        metin, meta = asistan_yanit(b, [], case.get("soru") or "x")
                    self.assertEqual(meta.get("hata"), case.get("beklenen_hata"))
                    continue

                if case.get("beklenen_hata") == "empty":
                    metin, meta = asistan_yanit(b, [], case.get("soru") or "")
                    self.assertEqual(meta.get("hata"), "empty")
                    continue

                captured = []

                def _fn(blob: str) -> str:
                    captured.append(blob)
                    return case.get("mock_yanit") or "Tamam."

                hist = case.get("history") or []
                metin, meta = asistan_yanit(
                    b, hist, case.get("soru") or "?", _call_fn=_fn
                )
                for frag in case.get("beklenen_icerir") or []:
                    self.assertIn(frag, metin)
                if "beklenen_grounding" in case:
                    self.assertEqual(
                        list(meta.get("grounding_uyari") or []),
                        list(case["beklenen_grounding"]),
                    )
                for frag in case.get("prompt_gecmis_icerir") or []:
                    self.assertTrue(captured)
                    self.assertIn(frag, captured[0])


class BildirimAiTest(unittest.TestCase):
    def test_bildirim_ai_mock(self):
        from bildirim_ai import bildirim_ai_ozet

        class H:
            ad = "THY"
            skor = 70
            sinyal = "GUCLU"

        olaylar = [("AL", "THYAO.IS", H())]
        metin = bildirim_ai_ozet(
            olaylar,
            rejim="Nötr",
            vix=18,
            force=True,
            _call_fn=lambda p: "THYAO yeni AL; temkinli izleyin.",
        )
        self.assertIn("THYAO", metin or "")

    def test_bildirim_ai_no_key(self):
        from bildirim_ai import bildirim_ai_ozet

        with patch("bildirim_ai.provider_ready", return_value=False):
            self.assertIsNone(bildirim_ai_ozet([("AL", "X", object())], force=True))


if __name__ == "__main__":
    unittest.main()
