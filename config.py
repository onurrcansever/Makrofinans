# -*- coding: utf-8 -*-
"""
TL Yatırım Karar Asistanı — Ayarlar ve Eşik Değerleri
========================================================
Bu dosya, sohbette tasarlanan kural tabanlı algoritmanın TÜM sabit
parametrelerini içerir. Stratejinizi değiştirmek istediğinizde
kodun başka hiçbir yerine dokunmanıza gerek yok, sadece burayı
düzenleyin.

ÖNEMLİ: Bu bir "otomatik alım-satım botu" DEĞİLDİR. Hiçbir işlemi
otomatik gerçekleştirmez, sadece verileri toplayıp size bir öneri
raporu üretir. Nihai kararı her zaman siz verirsiniz.
"""
import os
from dataclasses import dataclass, field
from typing import List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ------------------------------------------------------------------
# Portföy parametreleri
# ------------------------------------------------------------------
TOPLAM_EUR = float(os.getenv("TOPLAM_EUR", "30000"))
EUR_MEVDUAT_YILLIK_FAIZ = float(os.getenv("EUR_FAIZ", "0.025"))          # %2,5 brüt
TL_MEVDUAT_BRUT_FAIZ_VARSAYILAN = float(os.getenv("TL_FAIZ_VARSAYILAN", "0.40"))  # API'den çekilemezse kullanılır
TL_STOPAJ_ORANI = float(os.getenv("TL_STOPAJ", "0.15"))                  # bankanızdan teyit edin, vadeye göre değişir
KALAN_GUN = int(os.getenv("KALAN_GUN", "153"))                           # bugünden yıl sonuna kalan gün sayısı

# ------------------------------------------------------------------
# Kapı 2: CDS eşikleri -> maksimum TL tahsis oranı
# Liste (eşik_bp, üzerindeyse_maks_oran) şeklinde, büyükten küçüğe sıralı
# ------------------------------------------------------------------
CDS_ESIK_TABLOSU: List[Tuple[float, float]] = [
    (400.0, 0.00),   # CDS > 400bp  -> tahsis yok
    (300.0, 0.20),   # 300-400bp    -> maks %20
    (250.0, 0.35),   # 250-300bp    -> maks %35
    (0.0,   0.50),   # CDS < 250bp  -> maks %50
]

# ------------------------------------------------------------------
# Kapı 4: rezerv trend çarpanı
# ------------------------------------------------------------------
REZERV_DUSUS_CARPANI = 0.7   # son 4 haftada TCMB brüt rezervi azaldıysa tavanı bu oranla çarp
REZERV_BILINMIYOR_CARPANI = 0.85  # rezerv trendi yoksa Kapı 4 temkin çarpanı (EVDS key ile gerçek veri)

# Eurozone enflasyon varsayımı — EUR bazlı TL getiri tahmini için
EUR_ENFLASYON_VARSAYILAN = float(os.getenv("EUR_ENFLASYON_VARSAYILAN", "2.0"))

# ------------------------------------------------------------------
# Genel üst sınır — hiçbir koşulda aşılmaz
# ------------------------------------------------------------------
MUTLAK_TAVAN = 0.50

# ------------------------------------------------------------------
# Tranş (kademeli giriş) yapısı
# ------------------------------------------------------------------
TRANS_SAYISI = 3
TRANS_BEKLEME_HAFTA = 4

# ------------------------------------------------------------------
# Kapı 1: siyasi/jeopolitik risk taraması için anahtar kelimeler
# GDELT / haber API sonuçlarında bu kelimeler geçen makale sayısı
# belirlenen eşiği aşarsa "kriz modu" tetiklenir.
# ------------------------------------------------------------------
SIYASI_RISK_ANAHTAR_KELIMELER = [
    "kayyum atandı", "gözaltına alındı", "tutuklandı", "mutlak butlan",
    "OHAL ilan", "sermaye kontrolü", "erken seçim", "darbe girişimi",
    "devre kesici", "TCMB müdahale",
]
# Google News sorguları — GDELT'ten daha dar; magazin gözaltı haberlerini dışlar
SIYASI_GOOGLE_SORGULARI = [
    '"kayyum atandı" belediye Türkiye',
    '"erken seçim" Türkiye',
    '"OHAL ilan" OR "darbe girişimi" Türkiye',
    '"TCMB müdahale" OR "devre kesici" Türkiye',
    '"mutlak butlan" OR "sermaye kontrolü" Türkiye',
]
# Siyasi haber eşikleri — 14g taban medyanı ile birlikte kullanılır (siyasi_esik.py)
SIYASI_RISK_TABAN_VARSAYILAN = int(os.getenv("SIYASI_RISK_TABAN", "52"))
SIYASI_RISK_TABAN_GUN = int(os.getenv("SIYASI_RISK_TABAN_GUN", "14"))
SIYASI_RISK_TEMKIN_ESIGI = int(os.getenv("SIYASI_RISK_TEMKIN", "70"))   # TL fırsat kapat
SIYASI_RISK_KRIZ_ESIGI = int(os.getenv("SIYASI_RISK_KRIZ", "85"))     # KRİZ modu
SIYASI_RISK_TARAMA_SAAT = int(os.getenv("SIYASI_RISK_SAAT", "48"))    # haber penceresi
# Geriye dönük uyumluluk (dinamik kriz eşiği için siyasi_esik.esikler() kullanın)
SIYASI_RISK_MAKALE_ESIGI = SIYASI_RISK_KRIZ_ESIGI

# ------------------------------------------------------------------
# Savaş / jeopolitik şok taraması (enerji fiyatı kanalı için)
# ------------------------------------------------------------------
SAVAS_RISK_ANAHTAR_KELIMELER = [
    "Orta Doğu savaş", "İran çatışma", "Hürmüz Boğazı", "enerji fiyatı şoku",
    "Rusya Ukrayna eskalasyon", "petrol ambargo",
    "İran İsrail", "ABD İran", "Hürmüz kapat", "petrol fiyat", "İsrail saldırı",
]
# Google News TR sorguları — Türkçe finans medyası (Dünya, Mynet Finans vb.)
SAVAS_GOOGLE_SORGULARI = [
    "Hürmüz Boğazı İran",
    "İsrail İran savaş",
    "ABD İran Hürmüz",
    "İran ateşkes görüşme",
    "Küresel piyasalar İran",
]
SAVAS_RISK_ESIGI = int(os.getenv("SAVAS_RISK_ESIK", "4"))       # uyarı eşiği
SAVAS_RISK_YUKSEK_ESIGI = int(os.getenv("SAVAS_RISK_YUKSEK", "15"))  # tavan çarpanı
SAVAS_TAVAN_CARPANI = float(os.getenv("SAVAS_TAVAN_CARPANI", "0.90"))

# ------------------------------------------------------------------
# API anahtarları (ortam değişkenlerinden okunur, .env dosyasına yazın)
# ------------------------------------------------------------------
FRED_API_KEY = os.getenv("FRED_API_KEY", "")          # ABD Fed faizi için: https://fred.stlouisfed.org/docs/api/api_key.html
EVDS_API_KEY = os.getenv("EVDS_API_KEY", "")           # TCMB EVDS (ücretsiz): https://evds3.tcmb.gov.tr
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Bildirim kanalı: telegram | whatsapp | both
BILDIRIM_KANALI = os.getenv("BILDIRIM_KANALI", "telegram").lower()
# WhatsApp — CallMeBot (kişisel kullanım, ücretsiz): https://www.callmebot.com/blog/free-api-whatsapp-messages/
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "")       # örn. 40712345678 (ülke kodu, + yok)
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY", "")
# Meta WhatsApp Cloud API (alternatif — iş hesabı gerekir)
WHATSAPP_CLOUD_TOKEN = os.getenv("WHATSAPP_CLOUD_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_TO = os.getenv("WHATSAPP_TO", "")              # alıcı numara
NOTIFY_SINIRLI = os.getenv("NOTIFY_SINIRLI", "false").lower() in ("1", "true", "yes")
INVESTOR_RISK = os.getenv("INVESTOR_RISK", "orta")
INVESTOR_VADE = os.getenv("INVESTOR_VADE", "orta")

# ------------------------------------------------------------------
# Eski uyumluluk — artık kullanılmıyor (tüm makro veriler otomatik)
# ------------------------------------------------------------------
MANUAL_INPUTS_PATH = os.getenv("MANUAL_INPUTS_PATH", "manual_inputs.json")

# ------------------------------------------------------------------
# Çoklu varlık tahsisi — temel skorlar ve sınırlar
# ------------------------------------------------------------------
VARLIK_ETIKETLERI = {
    "eur_cash": "EUR mevduat",
    "usd_cash": "USD mevduat",
    "tl_deposit": "TL mevduat (TR)",
    "gold": "Altın",
    "silver": "Gümüş",
    "bist": "BIST 100",
    "crypto": "Kripto (BTC)",
}

TEMEL_SKORLAR = {
    "eur_cash": 55.0,
    "usd_cash": 45.0,
    "tl_deposit": 50.0,
    "gold": 50.0,
    "silver": 35.0,
    "bist": 40.0,
    "crypto": 25.0,
}

MIN_AGIRLIK = {
    "eur_cash": 0.10,
    "usd_cash": 0.05,
    "tl_deposit": 0.00,
    "gold": 0.05,
    "silver": 0.00,
    "bist": 0.00,
    "crypto": 0.00,
}

MAX_AGIRLIK = {
    "eur_cash": 0.55,
    "usd_cash": 0.30,
    "tl_deposit": 0.50,
    "gold": 0.35,
    "silver": 0.12,
    "bist": 0.15,
    "crypto": 0.08,
}

REGIME_STATE_PATH = os.getenv("REGIME_STATE_PATH", ".regime_state.json")
GIRDI_ONAY_STATE_PATH = os.getenv("GIRDI_ONAY_STATE_PATH", ".girdi_onay_state.json")

# ------------------------------------------------------------------
# Faz 1 — Girdi doğrulama ve sıçrama koruması
# ------------------------------------------------------------------
SANITY_BAND_GUN = int(os.getenv("SANITY_BAND_GUN", "90"))
SANITY_BAND_TOLERANS = float(os.getenv("SANITY_BAND_TOLERANS", "0.15"))
GIRDI_SICRAMA_YUZDE = float(os.getenv("GIRDI_SICRAMA_YUZDE", "0.10"))
CDS_SICRAMA_BP = float(os.getenv("CDS_SICRAMA_BP", "25"))
CDS_KAYNAK_FARK_BP = float(os.getenv("CDS_KAYNAK_FARK_BP", "20"))
TCMB_POLITIKA_SERI_KODU = "1_HAFTA_REPO"  # EVDS TP.APIFON4 politika faizi değildir

# ------------------------------------------------------------------
# Faz 2 — Rejim histerezis ve geçiş bölgesi
# ------------------------------------------------------------------
REJIM_ESIK_MARJ = float(os.getenv("REJIM_ESIK_MARJ", "0.05"))
REJIM_HISTEREZIS_TEYIT = int(os.getenv("REJIM_HISTEREZIS_TEYIT", "2"))
REJIM_GECIS_CDS_ESIKLERI: List[float] = [250.0, 280.0, 300.0, 400.0]
REJIM_GECIS_VIX_ESIK = float(os.getenv("REJIM_GECIS_VIX_ESIK", "16"))


@dataclass
class Esikler:
    """Kod içinde okunabilirlik için eşiklerin nesne hâli."""
    cds_kritik: float = 400.0
    cds_yuksek: float = 300.0
    cds_orta: float = 250.0
