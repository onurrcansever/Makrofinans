# -*- coding: utf-8 -*-
"""
Hisse/ETF sinyal alarmları — AL, DİKKAT, SAT (aşırı alım) değişince bildirim.
Önceki tarama durumuyla karşılaştırır; yalnızca yeni/değişen sinyallerde mesaj atar.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from alim_uygunluk import alim_aksiyon_kisa
from allocation_engine import tahsis_hesapla
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from notifier import bildirim_gonder
from al_bildirim import al_etiket_kisa, guncel_al_satirlar
from stock_scanner import SINYAL_ETIKET, tam_tarama

STATE_PATH = os.getenv("SIGNAL_STATE_PATH", ".signal_state.json")


def _profil_from_env() -> YatirimProfili:
    return YatirimProfili(
        risk=os.getenv("INVESTOR_RISK", "orta"),
        vade=os.getenv("INVESTOR_VADE", "orta"),
    )


def _durum(h) -> Dict[str, str]:
    return {
        "karar": getattr(h, "alim_uygun", "IZLE"),
        "sinyal": h.sinyal,
        "skor": str(round(h.skor or 0)),
    }


def _sat_mi(h) -> bool:
    return h.sinyal in ("ASIRI_ALIM", "UZAK_DUR")


def _oku(profil_key: str) -> Dict[str, Dict[str, str]]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("profil") != profil_key:
            return {}
        return data.get("semboller", {})
    except Exception:
        return {}


def _yaz(profil_key: str, semboller: Dict[str, Dict[str, str]]) -> None:
    payload = {
        "profil": profil_key,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "semboller": semboller,
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _degisimleri_bul(
    onceki: Dict[str, Dict[str, str]],
    hisseler: list,
) -> Tuple[List[Tuple[str, str, Any]], Dict[str, Dict[str, str]]]:
    """
    Dönüş: (tip, sembol, hisse) — tip: AL, DIKKAT, SAT, AL_KALDIRILDI
    """
    olaylar: List[Tuple[str, str, Any]] = []
    simdi: Dict[str, Dict[str, str]] = {}

    for h in hisseler:
        if h.fiyat is None:
            continue
        key = h.sembol
        cur = _durum(h)
        simdi[key] = cur
        old = onceki.get(key, {})
        old_karar = old.get("karar", "")
        new_karar = cur["karar"]

        if new_karar == "UYGUN" and old_karar != "UYGUN":
            olaylar.append(("AL", key, h))
        elif (
            config.NOTIFY_SINIRLI
            and new_karar == "SINIRLI"
            and old_karar not in ("UYGUN", "SINIRLI")
        ):
            olaylar.append(("DIKKAT", key, h))
        elif _sat_mi(h) and not _sat_mi_old(old):
            olaylar.append(("SAT", key, h))
        elif old_karar == "UYGUN" and new_karar in ("UYGUN_DEGIL", "IZLE"):
            olaylar.append(("AL_KALDIRILDI", key, h))

    return olaylar, simdi


def _sat_mi_old(old: Dict[str, str]) -> bool:
    return old.get("sinyal") in ("ASIRI_ALIM", "UZAK_DUR")


def alarm_metni_olustur(
    olaylar: List[Tuple[str, str, Any]],
    tahsis,
    profil: YatirimProfili,
    hisseler: Optional[list] = None,
) -> str:
    simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
    baslik = {
        "AL": "🟢 AL",
        "DIKKAT": "🟡 DİKKAT",
        "SAT": "🔴 SAT / Uzak dur",
        "AL_KALDIRILDI": "⚪ AL kaldırıldı",
    }
    satirlar = [
        f"YATIRIM SİNYALİ — {simdi}",
        f"Profil: {profil.ozet()} · Rejim: {tahsis.rejim.etiket}",
        "",
    ]
    for tip, _sym, h in olaylar:
        karar = alim_aksiyon_kisa(getattr(h, "alim_uygun", "IZLE"))
        tek = SINYAL_ETIKET.get(h.sinyal, h.sinyal)
        notu = (getattr(h, "alim_uygun_not", "") or "")[:80]
        satirlar.append(
            f"{baslik.get(tip, tip)} · {h.ad} ({h.sembol})"
        )
        satirlar.append(
            f"  {al_etiket_kisa(h)} · RSI {(h.rsi or 0):.0f} · {tek} · {karar}"
        )
        if notu:
            satirlar.append(f"  ↳ {notu}")
        # Cache-only ekler (API yok; yoksa sessiz atla)
        try:
            from bildirim_ekleri import sinyal_ek_satirlari
            satirlar.extend(sinyal_ek_satirlari(h))
        except Exception:
            pass
        satirlar.append("")

    if hisseler:
        satirlar += ["", "TÜM AL ADAYLARI:"]
        satirlar.extend(guncel_al_satirlar(hisseler))

    satirlar += [
        "—",
        "Finansal tavsiye değil; kural tabanlı karar desteği.",
        "Dashboard: localhost:8502",
    ]
    return "\n".join(satirlar)


def tarama_yap(snap: MacroSnapshot, profil: Optional[YatirimProfili] = None):
    profil = profil or _profil_from_env()
    tahsis = tahsis_hesapla(snap, profil)
    tarama = tam_tarama(tahsis.rejim.rejim, False, snap, haber_tara=False, profil=profil)
    return tahsis, tarama, profil


def kontrol_sinyal_ve_bildir(
    snap: MacroSnapshot,
    profil: Optional[YatirimProfili] = None,
    bildir: bool = True,
    ilk_calistirma_bildir: bool = False,
) -> Tuple[bool, List[Tuple[str, str, Any]]]:
    """
    Tarama yapar; AL/SAT değiştiyse Telegram/WhatsApp bildirimi gönderir.
    Dönüş: (bildirim_gonderildi, olay_listesi)
    """
    tahsis, tarama, profil = tarama_yap(snap, profil)
    profil_key = f"{profil.risk}_{profil.vade}"
    onceki = _oku(profil_key)
    ilk = not onceki

    olaylar, simdi = _degisimleri_bul(onceki, tarama.hisseler)
    _yaz(profil_key, simdi)

    if not olaylar:
        return False, []

    if ilk and not ilk_calistirma_bildir:
        return False, olaylar

    if not bildir:
        return False, olaylar

    metin = alarm_metni_olustur(olaylar, tahsis, profil, tarama.hisseler)
    ok = bildirim_gonder(metin)
    return ok, olaylar
