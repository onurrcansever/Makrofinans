# -*- coding: utf-8 -*-
"""
Rejim Değişim Alarmları
========================
Son bilinen rejimi kaydeder; değişince Telegram bildirimi gönderir.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import config
from allocation_engine import TahsisSonucu
from notifier import telegrama_gonder

STATE_PATH = os.getenv("REGIME_STATE_PATH", ".regime_state.json")


def _oku() -> Optional[Dict[str, Any]]:
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _yaz(rejim: str, tahsis: TahsisSonucu) -> None:
    payload = {
        "rejim": rejim,
        "rejim_etiket": tahsis.rejim.etiket,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "agirliklar": {k: round(v, 4) for k, v in tahsis.agirliklar.items()},
        "tl_tavan": tahsis.tl_tavan_oran,
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def rejim_degisti_mi(tahsis: TahsisSonucu) -> bool:
    onceki = _oku()
    if onceki is None:
        return True
    return onceki.get("rejim") != tahsis.rejim.rejim


def alarm_metni(tahsis: TahsisSonucu, onceki: Optional[Dict[str, Any]]) -> str:
    simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
    onceki_etiket = onceki.get("rejim_etiket", "—") if onceki else "İlk kayıt"
    satirlar = [
        f"⚠️ REJİM DEĞİŞİKLİĞİ — {simdi}",
        "",
        f"Önceki: {onceki_etiket}",
        f"Yeni:    {tahsis.rejim.etiket}",
        "",
        tahsis.rejim.aciklama,
        "",
        "Yeni tahsis özeti:",
    ]
    for k, w in sorted(tahsis.agirliklar.items(), key=lambda x: -x[1]):
        if w >= 0.01:
            tutar = config.TOPLAM_EUR * w
            satirlar.append(
                f"  {config.VARLIK_ETIKETLERI[k]}: %{w*100:.0f} ({tutar:,.0f} EUR)"
            )
    satirlar += [
        "",
        f"TL tavan (4 kapı): %{tahsis.tl_tavan_oran*100:.1f}",
        "",
        "Dashboard veya `python main.py` ile detaylı raporu inceleyin.",
    ]
    return "\n".join(satirlar)


def kontrol_ve_bildir(
    tahsis: TahsisSonucu,
    tam_rapor: str = "",
    telegram: bool = False,
    her_zaman_guncelle: bool = True,
) -> bool:
    """
    Rejim değiştiyse Telegram alarmı gönderir.
    Dönüş: alarm gönderildi mi?
    """
    onceki = _oku()
    degisti = rejim_degisti_mi(tahsis)
    alarm_gonderildi = False

    if degisti and telegram:
        metin = alarm_metni(tahsis, onceki)
        if telegrama_gonder(metin, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID):
            alarm_gonderildi = True
            if tam_rapor:
                telegrama_gonder(tam_rapor, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    if her_zaman_guncelle or onceki is None:
        _yaz(tahsis.rejim.rejim, tahsis)

    return alarm_gonderildi
