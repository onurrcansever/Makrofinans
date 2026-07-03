# -*- coding: utf-8 -*-
"""
Bildirim Katmanı
==================
Karar motorunun ürettiği sonucu okunabilir bir rapora çevirir ve
isteğe bağlı olarak Telegram veya WhatsApp'a gönderir.

Telegram bot kurulumu (5 dakika):
1. Telegram'da @BotFather ile konuşup /newbot komutuyla bot oluşturun,
   size bir TOKEN verecek -> .env dosyasına TELEGRAM_BOT_TOKEN olarak yazın.
2. Botunuzla bir kere mesajlaşın (örn. "merhaba" yazın).
3. https://api.telegram.org/bot<TOKEN>/getUpdates adresini tarayıcıda açıp
   "chat":{"id": ...} değerini bulun -> .env dosyasına TELEGRAM_CHAT_ID olarak yazın.

WhatsApp — CallMeBot (kişisel, ~2 dk):
1. https://www.callmebot.com/blog/free-api-whatsapp-messages/ adresindeki adımları izleyin.
2. WhatsApp'tan CallMeBot'a kayıt mesajı gönderin, API key alın.
3. .env: WHATSAPP_PHONE=40712345678, WHATSAPP_APIKEY=..., BILDIRIM_KANALI=whatsapp
"""
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import quote

import requests

import config
from decision_engine import KararSonucu
from decision_engine import PiyasaVerisi

if TYPE_CHECKING:
    from allocation_engine import TahsisSonucu
    from macro_data import MacroSnapshot


def rapor_metni_olustur(veri: PiyasaVerisi, sonuc: KararSonucu) -> str:
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    satirlar = [
        f"TL YATIRIM KARAR RAPORU — {tarih}",
        "=" * 40,
        "",
        "Girdi verileri:",
        f"  EUR/TRY spot        : {veri.eur_try}",
        f"  USD/TRY spot         : {veri.usd_try}",
        f"  Fed faizi             : {veri.fed_faizi}",
        f"  TCMB politika faizi   : {veri.tcmb_politika_faizi}",
        f"  5Y CDS (bp)            : {veri.cds_5y_bp}",
        f"  Rezerv artıyor mu?     : {veri.rezerv_artiyor}",
        f"  Siyasi risk haber sayısı: {veri.siyasi_risk_makale_sayisi}",
        "",
        "Algoritma adımları:",
    ]
    for a in sonuc.adimlar:
        satirlar.append(f"  - {a}")
    if sonuc.uyarilar:
        satirlar.append("")
        satirlar.append("Uyarılar:")
        for u in sonuc.uyarilar:
            satirlar.append(f"  ! {u}")
    satirlar += ["", sonuc.tavsiye_metni, "", "-" * 40,
                 "Bu bir finansal tavsiye değildir; kural tabanlı bir",
                 "karar-destek raporudur. Nihai karar size aittir."]
    return "\n".join(satirlar)


def portfoy_raporu_olustur(snap: "MacroSnapshot", tahsis: "TahsisSonucu") -> str:
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    v = snap.veri
    satirlar = [
        f"MAKRO PORTFÖY RAPORU — {tarih}",
        f"Veri kaynağı: {snap.veri_kaynak.upper()} | Rejim: {tahsis.rejim.etiket}",
        "=" * 48,
        "",
        "── Piyasa verileri ──",
        f"  EUR/TRY      : {v.eur_try}",
        f"  USD/TRY      : {v.usd_try}",
        f"  EUR/USD      : {snap.eur_usd}",
        f"  Fed faizi    : {v.fed_faizi}%",
        f"  TCMB faizi   : {v.tcmb_politika_faizi}%",
        f"  Enflasyon TR : {snap.enflasyon_tr_yillik}%",
        f"  CDS 5Y       : {v.cds_5y_bp} bp",
        f"  VIX          : {snap.vix}",
        f"  Altın USD/oz : {snap.altin_usd_oz}",
        f"  Gümüş USD/oz : {snap.gumus_usd_oz}",
        f"  BIST 100     : {snap.bist100}",
        f"  BTC USD      : {snap.btc_usd}",
        f"  Rezerv trend : {'↑' if v.rezerv_artiyor else '↓' if v.rezerv_artiyor is False else '?'}",
        f"  Siyasi risk  : {v.siyasi_risk_makale_sayisi} haber (48s)",
        "",
        "── Varlık skorları (0-100) ──",
    ]
    for k, s in sorted(tahsis.skorlar.items(), key=lambda x: -x[1]):
        satirlar.append(f"  {config.VARLIK_ETIKETLERI[k]:<22}: {s:.0f}")

    satirlar += ["", "── Önerilen tahsis ──"]
    for k in sorted(tahsis.agirliklar, key=tahsis.agirliklar.get, reverse=True):
        w = tahsis.agirliklar[k]
        if w >= 0.005:
            tutar = config.TOPLAM_EUR * w
            satirlar.append(
                f"  {config.VARLIK_ETIKETLERI[k]:<22}: %{w*100:5.1f}  ({tutar:,.0f} EUR)"
            )

    satirlar += ["", "── Algoritma adımları ──"]
    for a in tahsis.adimlar:
        satirlar.append(f"  • {a}")

    if tahsis.uyarilar:
        satirlar += ["", "── Uyarılar ──"]
        for u in tahsis.uyarilar:
            satirlar.append(f"  ! {u}")

    satirlar += [
        "",
        tahsis.tavsiye_metni,
        "",
        tahsis.rejim.aciklama,
        "",
        "-" * 48,
        "Bu bir finansal tavsiye değildir; kural tabanlı karar-destek raporudur.",
        "Nihai karar size aittir. Romanya vergi/beyan kuralları hesaplanmaz.",
    ]
    return "\n".join(satirlar)


def konsola_yazdir(metin: str) -> None:
    print(metin)


def whatsapp_callmebot_gonder(metin: str, phone: str, apikey: str) -> bool:
    """CallMeBot — kişisel WhatsApp (ücretsiz, API key gerekir)."""
    if not phone or not apikey:
        return False
    try:
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={quote(phone)}&text={quote(metin)}&apikey={quote(apikey)}"
        )
        r = requests.get(url, timeout=15)
        return r.status_code == 200 and "error" not in r.text.lower()[:200]
    except Exception as e:
        print(f"[UYARI] WhatsApp (CallMeBot) gönderimi başarısız: {e}")
        return False


def whatsapp_cloud_gonder(metin: str, token: str, phone_id: str, to: str) -> bool:
    """Meta WhatsApp Cloud API — iş hesabı gerekir."""
    if not token or not phone_id or not to:
        return False
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to.replace("+", ""),
                "type": "text",
                "text": {"body": metin[:4096]},
            },
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[UYARI] WhatsApp Cloud gönderimi başarısız: {e}")
        return False


def whatsapp_gonder(metin: str) -> bool:
    ok = False
    if config.WHATSAPP_CLOUD_TOKEN and config.WHATSAPP_PHONE_ID and config.WHATSAPP_TO:
        ok = whatsapp_cloud_gonder(
            metin,
            config.WHATSAPP_CLOUD_TOKEN,
            config.WHATSAPP_PHONE_ID,
            config.WHATSAPP_TO,
        ) or ok
    if config.WHATSAPP_PHONE and config.WHATSAPP_APIKEY:
        ok = whatsapp_callmebot_gonder(metin, config.WHATSAPP_PHONE, config.WHATSAPP_APIKEY) or ok
    if not ok:
        print("[UYARI] WhatsApp ayarları eksik — WHATSAPP_PHONE+APIKEY veya Cloud API doldurun.")
    return ok


def bildirim_gonder(metin: str) -> bool:
    """Telegram ve/veya WhatsApp — BILDIRIM_KANALI env ile seçilir."""
    kanal = config.BILDIRIM_KANALI
    ok = False
    if kanal in ("telegram", "both"):
        ok = telegrama_gonder(metin, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID) or ok
    if kanal in ("whatsapp", "both"):
        ok = whatsapp_gonder(metin) or ok
    if kanal not in ("telegram", "whatsapp", "both"):
        print(f"[UYARI] Geçersiz BILDIRIM_KANALI: {kanal}")
    return ok


def telegrama_gonder(metin: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id:
        print("[UYARI] Telegram ayarları eksik, bildirim atlanıyor.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": metin},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[UYARI] Telegram gönderimi başarısız: {e}")
        return False
