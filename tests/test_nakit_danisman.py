# -*- coding: utf-8 -*-
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from macro_data import demo_snapshot
from nakit_danisman import (
    vade_bilgisi,
    vade_sonu_plani,
    vadeli_mevduatlar,
    yeni_para_plani,
)
from varliklarim import VarlikPortfoy, VarlikPozisyon, VarlikStore


def _tahsis(agirliklar=None, tavan=0.15):
    return SimpleNamespace(
        agirliklar=agirliklar or {
            "eur_cash": 0.40,
            "gold": 0.20,
            "tl_deposit": 0.15,
            "usd_cash": 0.10,
            "bist": 0.10,
            "silver": 0.05,
        },
        tl_tavan_oran=tavan,
        rejim=SimpleNamespace(etiket="Enflasyon koruma"),
    )


def _store(pozisyonlar):
    pf = VarlikPortfoy(id="t1", ad="Test", pozisyonlar=pozisyonlar)
    return VarlikStore(aktif_id="t1", portfoyler=[pf])


def _mevduat_poz(tutar=1_200_000.0, vade_gun=94, faiz=42.0, alim=None):
    alim = alim or date.today() - timedelta(days=6)
    return VarlikPozisyon(
        id="mev1",
        tur="tl_mevduat",
        ad="YKB mevduat",
        miktar=tutar,
        maliyet=tutar,
        para_birimi="TL",
        alim_tarihi=alim.isoformat(),
        banka="Yapı Kredi",
        vade_gun=vade_gun,
        brut_faiz=faiz,
    )


def test_bos_portfoyde_hedef_agirliklarla_dagitir():
    plan = yeni_para_plani(200_000, "TL", demo_snapshot(), _tahsis(), varlik_store=None)
    assert plan is not None
    assert abs(sum(s.tutar_tl for s in plan.satirlar) - 200_000) < 1
    # En büyük satır en yüksek hedef ağırlığa gitmeli (eur_cash %40)
    assert plan.satirlar[0].sinif == "eur_cash"
    assert plan.satirlar[0].tutar_tl >= 200_000 * 0.35


def test_acik_kapatma_tl_agir_portfoyde_tl_onermez():
    # Portföyün tamamı TL mevduat — TL zaten tavanın çok üstünde, yeni para TL'ye gitmemeli
    store = _store([_mevduat_poz()])
    with patch("nakit_danisman._fiili_dagilim_tl", return_value={
        "eur_cash": 0.0, "usd_cash": 0.0, "tl_deposit": 1_200_000.0,
        "gold": 0.0, "silver": 0.0, "bist": 0.0, "crypto": 0.0,
    }):
        plan = yeni_para_plani(200_000, "TL", demo_snapshot(), _tahsis(tavan=0.15), varlik_store=store)
    assert plan is not None
    tl_satir = [s for s in plan.satirlar if s.sinif == "tl_deposit"]
    assert not tl_satir  # TL payı tavan üstünde — yeni TL önerilmez
    assert abs(sum(s.tutar_tl for s in plan.satirlar) - 200_000) < 1


def test_tl_tavani_asilmaz():
    plan = yeni_para_plani(
        1_000_000, "TL", demo_snapshot(),
        _tahsis(agirliklar={"tl_deposit": 0.5, "eur_cash": 0.5}, tavan=0.20),
        varlik_store=None,
    )
    assert plan is not None
    tl = sum(s.tutar_tl for s in plan.satirlar if s.sinif == "tl_deposit")
    assert tl <= 1_000_000 * 0.20 + 1  # tavan %20


def test_vade_bilgisi_net_tutar():
    p = _mevduat_poz(tutar=1_200_000, vade_gun=94, faiz=42.0, alim=date(2026, 7, 3))
    vb = vade_bilgisi(p, bugun=date(2026, 7, 9))
    assert vb is not None
    assert vb.vade_tarihi == date(2026, 10, 5)
    assert vb.kalan_gun == 88
    # brüt faiz = 1.2M × 0.42 × 94/365 ≈ 129.797 TL
    assert 125_000 < vb.brut_faiz_tl < 135_000
    assert vb.net_tl > vb.anapara_tl
    assert vb.net_tl < vb.anapara_tl + vb.brut_faiz_tl  # stopaj düşülmüş


def test_vade_bilgisi_vadesiz_pozisyon_none():
    p = _mevduat_poz(vade_gun=0)
    assert vade_bilgisi(p) is None


def test_vadeli_mevduatlar_siralama():
    p1 = _mevduat_poz(vade_gun=94)
    p2 = _mevduat_poz(vade_gun=30)
    p2.id = "mev2"
    store = _store([p1, p2])
    out = vadeli_mevduatlar(store)
    assert [v.pozisyon.id for v in out] == ["mev2", "mev1"]


def test_vade_sonu_plani_net_tutari_kullanir():
    p = _mevduat_poz(tutar=1_200_000, vade_gun=94, faiz=42.0, alim=date(2026, 7, 3))
    store = _store([p])
    vb = vade_bilgisi(p, bugun=date(2026, 7, 9))
    with patch("nakit_danisman._fiili_dagilim_tl", return_value={
        k: 0.0 for k in ["eur_cash", "usd_cash", "tl_deposit", "gold", "silver", "bist", "crypto"]
    }) as mock_fiili:
        plan = vade_sonu_plani(vb, demo_snapshot(), _tahsis(), varlik_store=store)
    assert plan is not None
    assert abs(plan.tutar_tl - round(vb.net_tl)) <= 1
    # Dolan mevduat fiili dağılımdan çıkarılmalı
    assert mock_fiili.call_args.kwargs["haric_pozisyon_id"] == "mev1"
    assert any("vadesinde net" in n for n in plan.notlar)
