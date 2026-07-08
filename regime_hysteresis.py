# -*- coding: utf-8 -*-
"""
Rejim skoru (−100..+100), dar BELİRSİZ bandı, teyit süresi.
Mevcut rejim_tespit imzasını bozmaz — v2 katmanı.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from macro_data import MacroSnapshot
from regime import REJIMLER, RejimSonucu, rejim_tespit
from siyasi_esik import esikler
from siyasi_etkin import kap1_haber_sayisi, siyasi_kriz_mi

STATE_PATH = getattr(config, "TL_ENGINE_STATE_PATH", ".tl_engine_state.json")

BELIRSIZ_ALT = float(os.getenv("REJIM_SKOR_BELIRSIZ_ALT", "-15"))
BELIRSIZ_UST = float(os.getenv("REJIM_SKOR_BELIRSIZ_UST", "15"))
REJIM_TEYIT = int(os.getenv("REJIM_SKOR_TEYIT", "2"))


def _oku() -> Dict[str, Any]:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _yaz(state: Dict[str, Any]) -> None:
    state["timestamp"] = datetime.now().isoformat(timespec="seconds")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def rejim_skoru_hesapla(
    snap: MacroSnapshot,
    etkin_siyasi: Optional[int] = None,
    ham_siyasi: Optional[int] = None,
) -> float:
    """
    −100 (TL riskli) .. +100 (TL fırsat penceresi).
    Ham rejim kurallarıyla uyumlu sürekli eksen.
    """
    v = snap.veri
    skor = 0.0
    es = esikler()

    cds = v.cds_5y_bp
    if cds is not None:
        if cds > 400:
            skor -= 80
        elif cds > 300:
            skor -= 50
        elif cds > 280:
            skor -= 30
        elif cds > 250:
            skor -= 15
        elif cds < 230:
            skor += 15
        elif cds < 250:
            skor += 8

    enflasyon = snap.enflasyon_tr_yillik or 35.0
    tcmb = v.tcmb_politika_faizi or (v.tl_mevduat_brut_faiz or 0.4) * 100
    reel = tcmb - enflasyon
    if reel > 3:
        skor += 25
    elif reel > 0:
        skor += 12
    else:
        skor -= 20

    raw_s = ham_siyasi if ham_siyasi is not None else (v.siyasi_risk_makale_sayisi or 0)
    etkin = etkin_siyasi if etkin_siyasi is not None else raw_s
    siyasi = kap1_haber_sayisi(raw_s, etkin) if etkin_siyasi is not None else raw_s
    if siyasi >= es["kriz"] and siyasi_kriz_mi(raw_s, etkin):
        skor -= 40
    elif siyasi >= es["temkin"]:
        skor -= 18
    elif siyasi < es["taban"]:
        skor += 5

    if v.tl_makro_risk_aktif:
        skor -= 22

    savas = v.savas_risk_makale_sayisi or 0
    if savas >= config.SAVAS_RISK_YUKSEK_ESIGI:
        skor -= 8
    elif savas >= config.SAVAS_RISK_ESIGI:
        skor -= 4

    vix = snap.vix
    if vix is not None:
        if vix > 25:
            skor -= 15
        elif vix < 16:
            skor += 10
        elif abs(vix - config.REJIM_GECIS_VIX_ESIK) <= 1.5:
            skor *= 0.85

    if v.rezerv_artiyor is False:
        skor -= 12
    elif v.rezerv_artiyor is True:
        skor += 5

    return max(-100.0, min(100.0, round(skor, 1)))


def skordan_rejim(skor: float) -> str:
    if skor >= BELIRSIZ_UST:
        return "TL_FIRSAT"
    if skor <= BELIRSIZ_ALT:
        return "EM_STRES"
    return "BELIRSIZ"


def _skor_rejim_sonucu(snap: MacroSnapshot, skor: float, adimlar: List[str]) -> RejimSonucu:
    hedef = skordan_rejim(skor)
    if hedef == "BELIRSIZ":
        komsu = ("TL_FIRSAT", "NOTR") if skor >= 0 else ("NOTR", "EM_STRES")
        adimlar.append(
            f"Rejim skoru {skor:+.0f} — dar BELİRSİZ bandı "
            f"[{BELIRSIZ_ALT:+.0f}, {BELIRSIZ_UST:+.0f}]"
        )
        return RejimSonucu(
            rejim="BELIRSIZ",
            etiket=REJIMLER["BELIRSIZ"],
            aciklama="Skor geçiş bölgesinde; komşu rejim ortalaması kullanılır.",
            guven=0.55,
            adimlar=adimlar,
            komşu_rejimler=komsu,
            gecis_notu=f"Skor {skor:+.0f}",
        )

    etiket = REJIMLER.get(hedef, hedef)
    if hedef == "TL_FIRSAT":
        aciklama = "TL mevduat fırsat penceresi — skor ekseni pozitif."
        guven = 0.72
    else:
        aciklama = "TL riskli bölge — skor ekseni negatif."
        guven = 0.68

    adimlar.append(f"Rejim skoru {skor:+.0f} → {hedef}")
    return RejimSonucu(
        rejim=hedef,
        etiket=etiket,
        aciklama=aciklama,
        guven=guven,
        adimlar=adimlar,
    )


def rejim_tespit_v2(
    snap: MacroSnapshot,
    etkin_siyasi: Optional[int] = None,
    ham_siyasi: Optional[int] = None,
    atla_teyit: bool = False,
) -> RejimSonucu:
    """
    Skor tabanlı rejim + 2 ardışık teyit (state.json).
    KRİZ/CDS>400 gibi sert kurallar ham rejimden devralınır.
    """
    ham = rejim_tespit(snap)
    if ham.rejim in ("KRIZ",):
        return ham

    v = snap.veri
    if v.cds_5y_bp is not None and v.cds_5y_bp > 400:
        return ham

    skor = rejim_skoru_hesapla(snap, etkin_siyasi=etkin_siyasi, ham_siyasi=ham_siyasi)
    adimlar = list(ham.adimlar)
    hedef = _skor_rejim_sonucu(snap, skor, adimlar)

    state = _oku()
    # Boş state: ham rejim taban — skor hedefi hemen rapora yansımaz
    aktif = state.get("son_rejim") or ham.rejim

    # Koşullar değiştiyse kilitli TL_FIRSAT'ı ham rejime indir
    if aktif == "TL_FIRSAT" and ham.rejim != "TL_FIRSAT":
        aktif = ham.rejim
        state["son_rejim"] = aktif
        state["bekleyen_rejim_skor"] = None

    raw_s = ham_siyasi if ham_siyasi is not None else (v.siyasi_risk_makale_sayisi or 0)
    etkin = etkin_siyasi if etkin_siyasi is not None else raw_s
    if etkin_siyasi is not None and siyasi_kriz_mi(raw_s, etkin):
        from regime_uyum import rejim_skorla_uyumla
        return rejim_skorla_uyumla(
            hedef, ham, snap, etkin_siyasi=etkin, ham_siyasi=raw_s
        )

    if hedef.rejim == "TL_FIRSAT" and ham.rejim != "TL_FIRSAT":
        from regime_uyum import rejim_skorla_uyumla
        return rejim_skorla_uyumla(
            hedef, ham, snap, etkin_siyasi=etkin_siyasi, ham_siyasi=ham_siyasi
        )

    if atla_teyit or state.get("rejim_yeniden_degerlendir"):
        state["son_rejim"] = hedef.rejim
        state["son_rejim_skor"] = skor
        state.pop("bekleyen_rejim_skor", None)
        state.pop("rejim_yeniden_degerlendir", None)
        _yaz(state)
        hedef.degisim_gerekce = f"Rejim skoru {skor:+.0f} — politika değişikliği / doğrudan atama"
        return hedef

    if hedef.rejim == aktif:
        state["son_rejim"] = aktif
        state["son_rejim_skor"] = skor
        state["bekleyen_rejim_skor"] = None
        _yaz(state)
        hedef.rejim = aktif
        hedef.etiket = REJIMLER.get(aktif, aktif)
        hedef.aciklama = _aciklama_duzelt(aktif, ham if aktif == ham.rejim else None)
        return hedef

    bekleyen = state.get("bekleyen_rejim_skor") or {}
    if bekleyen.get("rejim") == hedef.rejim:
        sayac = int(bekleyen.get("sayac", 0)) + 1
    else:
        sayac = 1

    if sayac >= REJIM_TEYIT:
        gerekce = f"Rejim {aktif}→{hedef.rejim}: skor {skor:+.0f} ({sayac}/{REJIM_TEYIT} teyit)"
        adimlar.append(gerekce)
        state["son_rejim"] = hedef.rejim
        state["son_rejim_skor"] = skor
        state["bekleyen_rejim_skor"] = None
        _yaz(state)
        hedef.adimlar = adimlar
        hedef.degisim_gerekce = gerekce
        return hedef

    state["bekleyen_rejim_skor"] = {"rejim": hedef.rejim, "sayac": sayac, "skor": skor}
    state["son_rejim"] = aktif
    _yaz(state)
    adimlar.append(
        f"Rejim değişimi bekliyor ({sayac}/{REJIM_TEYIT}): {aktif} → {hedef.rejim} (skor {skor:+.0f})"
    )
    donmus = deepcopy(hedef)
    donmus.rejim = aktif
    donmus.etiket = REJIMLER.get(aktif, aktif)
    donmus.aciklama = _aciklama_duzelt(aktif, ham if aktif == ham.rejim else None)
    donmus.adimlar = adimlar
    donmus.degisim_gerekce = ""
    return donmus


def _aciklama_duzelt(rejim_kodu: str, ham: Optional[RejimSonucu] = None) -> str:
    if ham and ham.rejim == rejim_kodu and ham.aciklama:
        return ham.aciklama
    sabit = {
        "TL_FIRSAT": "TL mevduat cazip; 4 kapılı tavan kuralları geçerli.",
        "NOTR": "Dengeli dağılım; mevcut makro verilere göre kademeli tahsis.",
        "EM_STRES": "Gelişen piyasa stresi; EUR/USD ve altın ağırlığı artırılmalı.",
        "KRIZ": "Pozisyon açmayın; likit ve güvenli varlıklara yönelin.",
        "BELIRSIZ": "Eşik yakınında; komşu rejim ortalaması kullanılır.",
        "RISK_ON": "Piyasa sakin; kontrollü risk iştahı değerlendirilebilir.",
        "ENFLASYON_KORUMA": "Satın alma gücü koruma modu; altın ve EUR ağırlığı artırılır.",
    }
    return sabit.get(rejim_kodu, REJIMLER.get(rejim_kodu, rejim_kodu))
