# -*- coding: utf-8 -*-
"""
Rejim kararlılığı — histerezis, geçiş bölgesi (BELIRSIZ), dondurma.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from girdi_dogrulama import GirdiDogrulamaSonucu
from macro_data import MacroSnapshot
from regime import REJIMLER, RejimSonucu, rejim_tespit

STATE_PATH = config.REGIME_STATE_PATH


def _oku() -> Dict[str, Any]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _yaz(payload: Dict[str, Any]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _gecis_bolgesi(snap: MacroSnapshot) -> Tuple[bool, str, Tuple[str, str]]:
    """Eşik ± marj bandında ise geçiş bölgesi."""
    v = snap.veri
    marj = config.REJIM_ESIK_MARJ
    cds = v.cds_5y_bp
    if cds is not None:
        for esik in config.REJIM_GECIS_CDS_ESIKLERI:
            if esik > 0 and abs(cds - esik) / esik <= marj:
                if cds <= esik:
                    komsu = ("RISK_ON" if esik == 250 else "NOTR", "EM_STRES" if esik >= 280 else "NOTR")
                    if esik == 280:
                        komsu = ("TL_FIRSAT", "EM_STRES")
                    elif esik == 300:
                        komsu = ("EM_STRES", "KRIZ")
                    elif esik == 400:
                        komsu = ("KRIZ", "EM_STRES")
                    else:
                        komsu = ("RISK_ON", "NOTR")
                else:
                    komsu = ("NOTR", "EM_STRES")
                return (
                    True,
                    f"CDS {cds:.0f} bp — eşik {esik:.0f} ±{marj*100:.0f}% geçiş bölgesi",
                    komsu,
                )
    vix = snap.vix
    esik_vix = config.REJIM_GECIS_VIX_ESIK
    if vix is not None and esik_vix > 0 and abs(vix - esik_vix) / esik_vix <= marj:
        return True, f"VIX {vix:.1f} — eşik {esik_vix} ±{marj*100:.0f}% geçiş bölgesi", ("RISK_ON", "NOTR")
    return False, "", ("NOTR", "NOTR")


def _gerekce_uret(onceki: str, yeni: str, snap: MacroSnapshot, state: dict) -> str:
    v = snap.veri
    parcalar = []
    onceki_snap = state.get("son_snap", {})
    if onceki_snap.get("cds") is not None and v.cds_5y_bp is not None:
        parcalar.append(f"CDS {onceki_snap['cds']:.0f}→{v.cds_5y_bp:.0f} bp")
    if onceki_snap.get("vix") is not None and snap.vix is not None:
        parcalar.append(f"VIX {onceki_snap['vix']:.1f}→{snap.vix:.1f}")
    tetik = ", ".join(parcalar) if parcalar else "makro girdi güncellemesi"
    return f"Rejim {onceki}→{yeni}: tetikleyen girdi = {tetik}"


def rejim_kararli_uygula(
    snap: MacroSnapshot,
    girdi: Optional[GirdiDogrulamaSonucu] = None,
) -> RejimSonucu:
    """Ham rejim + histerezis + girdi dondurma."""
    ham = rejim_tespit(snap)
    state = _oku()
    aktif = state.get("aktif_rejim") or ham.rejim
    adimlar = list(ham.adimlar)

    if girdi and girdi.rejim_donduruldu:
        adimlar.append(
            "Girdi sıçraması — rejim donduruldu (onay bekleyen: "
            + ", ".join(girdi.onay_bekleyen)
            + ")"
        )
        donmus = deepcopy(ham)
        donmus.rejim = aktif
        donmus.etiket = REJIMLER.get(aktif, aktif)
        donmus.adimlar = adimlar
        donmus.degisim_gerekce = ""
        donmus.donduruldu = True
        return donmus

    gecis, gecis_not, komsu = _gecis_bolgesi(snap)
    if gecis:
        adimlar.append(gecis_not)
        belirsiz = RejimSonucu(
            rejim="BELIRSIZ",
            etiket="Belirsiz / geçiş bölgesi",
            aciklama="Eşik yakınında; dağılım iki komşu rejimin ortalaması kullanılır.",
            guven=0.5,
            adimlar=adimlar,
            komşu_rejimler=komsu,
            gecis_notu=gecis_not,
        )
        return belirsiz

    if ham.rejim == aktif:
        state["bekleyen_rejim"] = None
        state["aktif_rejim"] = aktif
        state["son_snap"] = {
            "cds": snap.veri.cds_5y_bp,
            "vix": snap.vix,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        _yaz(state)
        ham.degisim_gerekce = ""
        ham.donduruldu = False
        return ham

    bekleyen = state.get("bekleyen_rejim") or {}
    if bekleyen.get("rejim") == ham.rejim:
        sayac = int(bekleyen.get("sayac", 0)) + 1
    else:
        sayac = 1

    if sayac >= config.REJIM_HISTEREZIS_TEYIT:
        gerekce = _gerekce_uret(aktif, ham.rejim, snap, state)
        adimlar.append(gerekce)
        ham.degisim_gerekce = gerekce
        ham.donduruldu = False
        state["aktif_rejim"] = ham.rejim
        state["bekleyen_rejim"] = None
        state["son_snap"] = {
            "cds": snap.veri.cds_5y_bp,
            "vix": snap.vix,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        _yaz(state)
        ham.adimlar = adimlar
        return ham

    state["bekleyen_rejim"] = {"rejim": ham.rejim, "sayac": sayac}
    state["aktif_rejim"] = aktif
    _yaz(state)
    adimlar.append(
        f"Rejim değişimi bekliyor teyit ({sayac}/{config.REJIM_HISTEREZIS_TEYIT}): "
        f"{aktif} → {ham.rejim}"
    )
    bekleyen_sonuc = deepcopy(ham)
    bekleyen_sonuc.rejim = aktif
    bekleyen_sonuc.etiket = REJIMLER.get(aktif, aktif)
    bekleyen_sonuc.adimlar = adimlar
    bekleyen_sonuc.degisim_gerekce = ""
    bekleyen_sonuc.donduruldu = False
    return bekleyen_sonuc
