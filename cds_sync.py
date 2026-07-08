# -*- coding: utf-8 -*-
"""
CDS güncelleme hattı — Bloomberg Terminal + Investing.com otomatik.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

MANUAL_PATH = os.path.join(os.path.dirname(__file__), "manual_inputs.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "cds_history.jsonl")


@dataclass
class CdsKaynakOlcum:
    ad: str
    deger: Optional[float]
    kaynak: str = ""
    hata: str = ""
    gecikmeli: bool = False
    gecikme_gun: int = 0


@dataclass
class CdsGuncellemeSonucu:
    kaynaklar: List[CdsKaynakOlcum] = field(default_factory=list)
    efektif: Optional[float] = None
    efektif_kaynak: str = ""
    otomatik_median: Optional[float] = None
    otomatik_dogrulandi: bool = False
    bloomberg_erisim: bool = False
    uyarilar: List[str] = field(default_factory=list)
    bildirim_gonderildi: bool = False


def _rel_fark(a: float, b: float) -> float:
    ort = (a + b) / 2.0
    if ort <= 0:
        return 0.0
    return abs(a - b) / ort


def cds_kaynaklari_topla() -> List[CdsKaynakOlcum]:
    from cds_bloomberg import turkiye_cds_5y_bloomberg_blp
    from data_sources import (
        turkiye_cds_5y_investing_detay,
        turkiye_cds_5y_investing_kapanis,
        turkiye_cds_5y_wgb,
    )

    cikis: List[CdsKaynakOlcum] = []

    blp = turkiye_cds_5y_bloomberg_blp()
    if blp:
        cikis.append(CdsKaynakOlcum(ad="bloomberg", deger=blp[0], kaynak=blp[1]))
    else:
        cikis.append(CdsKaynakOlcum(
            ad="bloomberg",
            deger=None,
            hata="Terminal/BLPAPI yok — BLOOMBERG_* .env ayarları",
        ))

    detay = turkiye_cds_5y_investing_detay()
    if detay:
        cikis.append(CdsKaynakOlcum(
            ad="investing_canli",
            deger=detay.deger,
            kaynak=detay.kaynak,
            gecikmeli=detay.gecikmeli,
            gecikme_gun=detay.gecikme_gun,
        ))
    else:
        cikis.append(CdsKaynakOlcum(ad="investing_canli", deger=None, hata="Veri yok"))

    for ad, fn in (
        ("investing_kapanis", turkiye_cds_5y_investing_kapanis),
        ("wgb", turkiye_cds_5y_wgb),
    ):
        try:
            sonuc = fn()
            if sonuc:
                cikis.append(CdsKaynakOlcum(ad=ad, deger=sonuc[0], kaynak=sonuc[1]))
            else:
                cikis.append(CdsKaynakOlcum(ad=ad, deger=None, hata="Veri yok"))
        except Exception as e:
            cikis.append(CdsKaynakOlcum(ad=ad, deger=None, hata=str(e)))

    return cikis


def cds_gecmis_ekle(kaynaklar: Dict[str, float], efektif: Optional[float], not_metni: str = "") -> None:
    try:
        satir = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kaynaklar": kaynaklar,
            "efektif": efektif,
            "not": not_metni,
        }
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(satir, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _kaynak_listesi_cds_sonucundan(cds) -> List[CdsKaynakOlcum]:
    """Tek CDS hattından sidebar tablosu — ayrı API turu yok."""
    from cds_bloomberg import bloomberg_terminal_erisimli

    meta_etiket = {
        "bloomberg": "Bloomberg Terminal BLPAPI",
        "investing_canli": "Investing.com canlı",
        "investing_kapanis": "Investing.com kapanış",
        "wgb": "WorldGovernmentBonds",
        "manual_yedek": "manual_inputs.json (otomatik yedek)",
    }
    cikis: List[CdsKaynakOlcum] = []
    for ad in ("bloomberg", "investing_canli", "investing_kapanis", "wgb", "manual_yedek"):
        if ad in cds.kaynaklar:
            cikis.append(
                CdsKaynakOlcum(
                    ad=ad,
                    deger=cds.kaynaklar[ad],
                    kaynak=meta_etiket.get(ad, ad),
                )
            )
        elif ad == "bloomberg":
            cikis.append(
                CdsKaynakOlcum(
                    ad=ad,
                    deger=None,
                    hata=(
                        "Terminal/BLPAPI yok — BLOOMBERG_* .env ayarları"
                        if not bloomberg_terminal_erisimli()
                        else "Veri yok"
                    ),
                )
            )
        elif ad in ("investing_canli", "investing_kapanis") and ad not in cds.kaynaklar:
            cikis.append(CdsKaynakOlcum(ad=ad, deger=None, hata="Veri yok"))
    return cikis


def cds_guncelleme_calistir(
    *,
    bildir: bool = False,
    taze: bool = False,
    tick: int = 0,
) -> CdsGuncellemeSonucu:
    from cds_bloomberg import bloomberg_terminal_erisimli
    from cds_guven import cds_guvenli_al, cds_sonuc_al, cds_sonuc_kaydet

    onceden = cds_sonuc_al(tick) if tick >= 0 else None
    if onceden is not None:
        cds = onceden
    else:
        cds = cds_guvenli_al(taze=taze)
        cds_sonuc_kaydet(cds, tick)

    sonuc = CdsGuncellemeSonucu()
    sonuc.kaynaklar = _kaynak_listesi_cds_sonucundan(cds)
    sonuc.bloomberg_erisim = bloomberg_terminal_erisimli()
    sonuc.efektif = cds.deger
    sonuc.efektif_kaynak = cds.kaynak
    sonuc.uyarilar = list(cds.uyari)
    sonuc.otomatik_dogrulandi = cds.dogrulandi

    bb = cds.kaynaklar.get("bloomberg")
    inv = cds.kaynaklar.get("investing_canli") or cds.kaynaklar.get("investing_kapanis")
    if bb and inv:
        sonuc.otomatik_median = (bb + inv) / 2.0
    elif inv:
        sonuc.otomatik_median = inv
    elif bb:
        sonuc.otomatik_median = bb

    kaynak_dict = {k.ad: k.deger for k in sonuc.kaynaklar if k.deger is not None}
    cds_gecmis_ekle(kaynak_dict, cds.deger, "; ".join(sonuc.uyarilar[:2]))

    if bildir:
        try:
            import notifier
            satirlar = [
                "CDS otomatik güncelleme",
                f"Efektif: {cds.deger:.0f} bp — {cds.kaynak}",
            ]
            for k in sonuc.kaynaklar:
                if k.deger is not None:
                    satirlar.append(f"  {k.ad}: {k.deger:.0f} ({k.kaynak})")
                elif k.ad == "bloomberg":
                    satirlar.append("  bloomberg: erişim yok")
            for u in sonuc.uyarilar[:3]:
                satirlar.append(u)
            sonuc.bildirim_gonderildi = notifier.bildirim_gonder("\n".join(satirlar))
        except Exception:
            pass

    return sonuc


def cds_durum_metni() -> str:
    from cds_bloomberg import bloomberg_terminal_erisimli

    s = cds_guncelleme_calistir(bildir=False)
    satirlar = ["=== CDS Otomatik Kaynaklar ==="]
    satirlar.append(
        f"  Bloomberg Terminal: {'bağlı' if bloomberg_terminal_erisimli() else 'yok (BLPAPI/Terminal gerekli)'}"
    )
    for k in s.kaynaklar:
        if k.deger is not None:
            gec = f" [+{k.gecikme_gun}g gecikme]" if k.gecikmeli else ""
            satirlar.append(f"  {k.ad:18} {k.deger:7.2f} bp  — {k.kaynak}{gec}")
        else:
            satirlar.append(f"  {k.ad:18}   —     —  ({k.hata or 'yok'})")
    if s.efektif is not None:
        satirlar.append(f"  → Rejimde kullanılan: {s.efektif:.0f} bp ({s.efektif_kaynak[:60]})")
    for u in s.uyarilar:
        satirlar.append(f"  ⚠ {u}")
    return "\n".join(satirlar)
