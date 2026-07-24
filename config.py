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
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ------------------------------------------------------------------
# Portföy parametreleri
# ------------------------------------------------------------------
TOPLAM_EUR = float(os.getenv("TOPLAM_EUR", "30000"))
# TR bankalarında EUR mevduat gerçekte %0,01–0,25 brüt (2026, Akbank/ING/YKB).
# Canlı kaynak yok — kendi bankanızın teklifini .env EUR_FAIZ ile girin (örn. 0.0025 = %0,25).
EUR_MEVDUAT_YILLIK_FAIZ = float(os.getenv("EUR_FAIZ", "0.0025"))         # %0,25 brüt varsayılan
USD_MEVDUAT_YILLIK_FAIZ = float(os.getenv("USD_FAIZ", "0.015"))          # %1,5 brüt varsayılan
TL_MEVDUAT_BRUT_FAIZ_VARSAYILAN = float(os.getenv("TL_FAIZ_VARSAYILAN", "0.40"))  # API'den çekilemezse kullanılır
TL_STOPAJ_ORANI = float(os.getenv("TL_STOPAJ", "0.15"))                  # eski alias — TL_STOPAJ_ORAN kullanın
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
    "OHAL ilan", "sermaye kontrolü", "darbe girişimi",
    "devre kesici", "TCMB müdahale",
]
# Google News sorguları — GDELT'ten daha dar; magazin gözaltı haberlerini dışlar
SIYASI_GOOGLE_SORGULARI = [
    '"kayyum atandı" belediye Türkiye',
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
# TL makro haber riski — faiz indirimi beklentisi, erken seçim sıçraması
# (Orta Doğu jeopolitiğinden ayrı; doğrudan kur/TL kanalı)
# ------------------------------------------------------------------
TL_MAKRO_FAIZ_SORGULARI = [
    '"faiz indirimi" beklentisi TCMB Türkiye',
    '"faiz düşürme" beklentisi Türkiye',
    '"politika faizi" indirim PPK Türkiye',
]
TL_MAKRO_SECIM_SORGULARI = [
    '"erken seçim kararı" Türkiye',
    '"seçim tarihi" ilan Türkiye',
    '"sandığa" erken seçim Türkiye',
]
# Geriye dönük alias — tek sorgu yerine karar odaklı liste
TL_MAKRO_SECIM_SORGUSU = TL_MAKRO_SECIM_SORGULARI[0]
TL_MAKRO_SECIM_TABAN_VARSAYILAN = int(os.getenv("TL_MAKRO_SECIM_TABAN", "20"))
TL_MAKRO_SECIM_KARAR_ESIGI = int(os.getenv("TL_MAKRO_SECIM_KARAR_ESIK", "20"))
TL_MAKRO_SECIM_ANORMAL_MUTLAK = int(os.getenv("TL_MAKRO_SECIM_ANORMAL_MUTLAK", "45"))
TL_MAKRO_FAIZ_ESIGI = int(os.getenv("TL_MAKRO_FAIZ_ESIK", "15"))
TL_MAKRO_FAIZ_TABAN_VARSAYILAN = int(os.getenv("TL_MAKRO_FAIZ_TABAN", "4"))
TL_MAKRO_TABAN_GUN = int(os.getenv("TL_MAKRO_TABAN_GUN", "14"))
TL_MAKRO_ANORMAL_CARPAN = float(os.getenv("TL_MAKRO_ANORMAL_CARPAN", "2.0"))
TL_MAKRO_ANORMAL_ARTIS = int(os.getenv("TL_MAKRO_ANORMAL_ARTIS", "6"))
TL_MAKRO_TAVAN_CARPANI = float(os.getenv("TL_MAKRO_TAVAN_CARPANI", "0.85"))

# ------------------------------------------------------------------
# TL karar motoru v2 — state, PPK/FOMC takvimi
# ------------------------------------------------------------------
TL_ENGINE_STATE_PATH = os.getenv("TL_ENGINE_STATE_PATH", ".tl_engine_state.json")
PPK_BEKLE_GUN = int(os.getenv("PPK_BEKLE_GUN", "7"))

from datetime import date as _date  # noqa: E402

# TCMB resmi PPK 2026 (karar günü): https://www.tcmb.gov.tr/.../PPK/2026
TCMB_PPK_TAKVIM = [
    _date(2026, 1, 22), _date(2026, 3, 12), _date(2026, 4, 22), _date(2026, 6, 11),
    _date(2026, 7, 23), _date(2026, 9, 10), _date(2026, 10, 22), _date(2026, 12, 10),
]
# Fed FOMC 2026 (toplantı son günü / karar): federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_TAKVIM = [
    _date(2026, 1, 28), _date(2026, 3, 18), _date(2026, 4, 29), _date(2026, 6, 17),
    _date(2026, 7, 29), _date(2026, 9, 16), _date(2026, 10, 28), _date(2026, 12, 9),
]

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
# WhatsApp özet alarmı: değişiklik olmasa da gönder (günde 4 kez — 10/13/15/18 TR)
OZET_ALARM_HER_ZAMAN = os.getenv("OZET_ALARM_HER_ZAMAN", "1").lower() in ("1", "true", "yes")
# WhatsApp özetinde AL listesi — 0 = tüm adaylar (varsayılan)
OZET_AL_MAX_HISSE = int(os.getenv("OZET_AL_MAX_HISSE", "0"))
OZET_AL_MAX_ETF = int(os.getenv("OZET_AL_MAX_ETF", "0"))
# WhatsApp özetinde pozisyon tablosu (Sinyal · Öneri · K/Z)
OZET_POZISYON_TABLO = os.getenv("OZET_POZISYON_TABLO", "1").lower() in ("1", "true", "yes")
OZET_GOSTERIM_PB = os.getenv("OZET_GOSTERIM_PB", "EUR").upper()
OZET_POZ_MAX = int(os.getenv("OZET_POZ_MAX", "0"))  # 0 = tüm pozisyonlar
INVESTOR_RISK = os.getenv("INVESTOR_RISK", "orta")
INVESTOR_VADE = os.getenv("INVESTOR_VADE", "kisa_6")

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
REJIM_ESIK_MARJ = float(os.getenv("REJIM_ESIK_MARJ", "0.025"))
REJIM_HISTEREZIS_TEYIT = int(os.getenv("REJIM_HISTEREZIS_TEYIT", "2"))
# Yalnızca belirsiz geçişler — 250/400 gibi sert eşikler ham rejimde kalır
REJIM_GECIS_CDS_ESIKLERI: List[float] = [280.0, 300.0]
REJIM_GECIS_VIX_ESIK = float(os.getenv("REJIM_GECIS_VIX_ESIK", "16"))

# ------------------------------------------------------------------
# Faz 3 — Senaryo analizi
# ------------------------------------------------------------------
SENARYO_KUR_SOKU_CARPANI = float(os.getenv("SENARYO_KUR_SOKU_CARPANI", "1.05"))
SENARYO_CDS_STRES_BP = float(os.getenv("SENARYO_CDS_STRES_BP", "280"))
SENARYO_TCMB_DEGISIM_BP = float(os.getenv("SENARYO_TCMB_DEGISIM_BP", "300"))

# ------------------------------------------------------------------
# Faz 4 — Stopaj, TMSF (7316/GVK 2024+: bireysel TL vadeli mevduat %15)
# ------------------------------------------------------------------
TL_STOPAJ_ORAN = float(os.getenv("TL_STOPAJ_ORAN", os.getenv("TL_STOPAJ", "0.15")))
TL_STOPAJ_KAYNAK = os.getenv(
    "TL_STOPAJ_KAYNAK",
    "GVK Md.94 — bireysel vadeli TL mevduat stopajı %15 "
    "(2024+ varsayılan; dönemsel dilimler değişebilir — bankanızdan teyit edin)",
)
TL_STOPAJ_TABLOSU: List[Tuple[int, float]] = [
    (99999, TL_STOPAJ_ORAN),
]
DOVIZ_STOPAJ_ORANI = float(os.getenv("DOVIZ_STOPAJ", "0.25"))
TMSF_SIGORTA_LIMITI_TL = float(os.getenv("TMSF_SIGORTA_LIMITI_TL", "650000"))
BACKTEST_REJIM_MIN_ORAN = float(os.getenv("BACKTEST_REJIM_MIN_ORAN", "10"))
BACKTEST_UYARI_SHARPE_FARK = float(os.getenv("BACKTEST_UYARI_SHARPE_FARK", "0.25"))

# Profil bazlı pasif referans — dinamik katmanla karşılaştırma (rejim değiştirmez)
STATIK_REFERANS_AGIRLIKLARI: Dict[str, Dict[str, float]] = {
    "dusuk": {
        "eur_cash": 0.45, "usd_cash": 0.15, "gold": 0.28, "tl_deposit": 0.05,
        "silver": 0.02, "bist": 0.03, "crypto": 0.0,
    },
    "orta": {
        "eur_cash": 0.35, "usd_cash": 0.12, "gold": 0.28, "tl_deposit": 0.08,
        "silver": 0.05, "bist": 0.07, "crypto": 0.05,
    },
    "yuksek": {
        "eur_cash": 0.25, "usd_cash": 0.12, "gold": 0.22, "tl_deposit": 0.10,
        "silver": 0.08, "bist": 0.15, "crypto": 0.08,
    },
}

# Kripto yalnızca RISK_ON + yeterli skor iken tahsis edilir (0 aksi halde)
KRIPTO_MIN_SKOR = float(os.getenv("KRIPTO_MIN_SKOR", "55"))
# Tahsis yeniden dengeleme eşiği (oran puanı, örn. 0.03 = %3)
REBALANCE_MIN_PP = float(os.getenv("REBALANCE_MIN_PP", "0.03"))
# Tarama AL yokken BIST dilimi: makro ağırlığın yarısı ve mutlak tavan
BIST_SINYAL_YOK_CARPAN = float(os.getenv("BIST_SINYAL_YOK_CARPAN", "0.50"))
BIST_SINYAL_YOK_MAX = float(os.getenv("BIST_SINYAL_YOK_MAX", "0.04"))
KRIPTO_SADECE_RISK_ON = os.getenv("KRIPTO_SADECE_RISK_ON", "1").strip().lower() not in ("0", "false", "no")

# TL mevduat reel negatifken tahsis/sinyal üst sınırı (profil vadesi banka net − enflasyon)
TL_REEL_NEGATIF_ESIK = float(os.getenv("TL_REEL_NEGATIF_ESIK", "0"))
TL_REEL_NEGATIF_MAX_ORAN = float(os.getenv("TL_REEL_NEGATIF_MAX", "0.05"))
TL_REEL_COK_NEGATIF_ESIK = float(os.getenv("TL_REEL_COK_NEGATIF_ESIK", "-2"))
TL_REEL_COK_NEGATIF_MAX_ORAN = float(os.getenv("TL_REEL_COK_NEGATIF_MAX", "0.02"))
TL_REEL_SKOR_TAVAN_NEGATIF = float(os.getenv("TL_REEL_SKOR_TAVAN", "45"))

# TL_FIRSAT dışı rejimlerde TL üst sınırı (makro skor–rejim tutarlılığı)
TL_REJIM_DISI_MAX_ORAN = float(os.getenv("TL_REJIM_DISI_MAX", "0.12"))
TL_REJIM_DISI_SKOR_TAVAN = float(os.getenv("TL_REJIM_DISI_SKOR", "58"))

# Risk profiline göre TL üst sınırı — carry trade düşük riskte kısıtlı (rejim TL_FIRSAT değilken)
TL_DUSUK_RISK_MAX_ORAN = float(os.getenv("TL_DUSUK_RISK_MAX", "0.05"))
TL_DUSUK_RISK_FIRSAT_MAX = float(os.getenv("TL_DUSUK_RISK_FIRSAT_MAX", "0.10"))
TL_ORTA_RISK_FIRSAT_MAX = float(os.getenv("TL_ORTA_RISK_FIRSAT_MAX", "0.22"))
TL_YUKSEK_RISK_FIRSAT_MAX = float(os.getenv("TL_YUKSEK_RISK_FIRSAT_MAX", "0.32"))
TL_YUKSEK_RISK_DISI_MAX = float(os.getenv("TL_YUKSEK_RISK_DISI_MAX", "0.15"))

# Altın momentum düşüşünde tahsis/sinyal yumuşatma (son 3 ay %)
ALTIN_MOMENTUM_ESIK = float(os.getenv("ALTIN_MOMENTUM_ESIK", "-8"))
ALTIN_MOMENTUM_MAX_ORAN = float(os.getenv("ALTIN_MOMENTUM_MAX", "0.18"))
ALTIN_MOMENTUM_SKOR_TAVAN = float(os.getenv("ALTIN_MOMENTUM_SKOR", "55"))

# Dinamik araç seçici — maliyet / makas / dilim payları (yüzde puan veya oran)
ALTIN_FIZIKI_MAKAS_PCT = float(os.getenv("ALTIN_FIZIKI_MAKAS_PCT", "2.0"))
FX_CEVIRIM_MAKAS_PCT = float(os.getenv("FX_CEVIRIM_MAKAS_PCT", "0.30"))
ETF_TER_VARSAYILAN = float(os.getenv("ETF_TER_VARSAYILAN", "0.07"))
ETF_SGLD_TER = float(os.getenv("ETF_SGLD_TER", "0.12"))
ARAC_MIN_FARK_PCT = float(os.getenv("ARAC_MIN_FARK_PCT", "0.50"))
# Sınıf içi dilimler (tl_deposit / eur+usd içinden kesilir — çift sayım yok)
TEFAS_DILIM_PAY = float(os.getenv("TEFAS_DILIM_PAY", "0.35"))
ETF_DILIM_PAY = float(os.getenv("ETF_DILIM_PAY", "0.45"))
# TEFAS stopaj varsayılan iktisap dilimi (matris: tefas_stopaj.py)
TEFAS_STOPAJ_VARSAYILAN_DONEM = os.getenv(
    "TEFAS_STOPAJ_VARSAYILAN_DONEM", "yeni_20250709"
)
# ETF sinyal köprüsü: zayıf rejimde hisse-ETF payını FX mevduata geri it
ETF_SINYAL_YOK_CARPAN = float(os.getenv("ETF_SINYAL_YOK_CARPAN", "0.40"))

# Hisse taraması — AL adayı yokken kanonik tablo üst sınırı
TARAMA_KANONIK_MAX_SATIR = int(os.getenv("TARAMA_KANONIK_MAX", "15"))

# Vade sonu net tutar simülasyonu — boş/0 ise portföyün önerilen TL dilimi kullanılır
_tl_mevduat_tutar_raw = os.getenv("TL_MEVDUAT_TUTAR_TL", "").strip()
TL_MEVDUAT_TUTAR_TL: Optional[float] = (
    float(_tl_mevduat_tutar_raw) if _tl_mevduat_tutar_raw else None
)

# ------------------------------------------------------------------
# Faz 7 — Temel skor (ETF/hisse) ve bileşik karar
# ------------------------------------------------------------------
BILESKE_TEKNIK_AGIRLIK = float(os.getenv("BILESKE_TEKNIK_AGIRLIK", "0.40"))
BILESKE_TEMEL_AGIRLIK = float(os.getenv("BILESKE_TEMEL_AGIRLIK", "0.60"))
BILESKE_AL_ESIK = float(os.getenv("BILESKE_AL_ESIK", "80"))
BILESKE_DIkkat_ESIK = float(os.getenv("BILESKE_DIkkat_ESIK", "65"))

# Temel skor UI — geliştirme varsayılanı FORCE=1 (deneysel banner).
# Prod: FUND_SCORE_UI_FORCE=0 ve yalnızca FAZ5 gate + FUND_SCORE_UI=1.
FUND_SCORE_UI = os.getenv("FUND_SCORE_UI", "0").strip().lower() in ("1", "true", "yes")
FUND_SCORE_UI_FORCE = os.getenv("FUND_SCORE_UI_FORCE", "1").strip().lower() in (
    "1", "true", "yes",
)
BILESKE_BEKLE_ESIK = float(os.getenv("BILESKE_BEKLE_ESIK", "50"))

# Tek hisse AL — trend/momentum hikâye filtresi (portföy + Karar=AL)
AL_TEK_HISSE_ZIRVE_52H_MAX = float(os.getenv("AL_TEK_HISSE_ZIRVE_52H_MAX", "74"))
AL_TEK_HISSE_SMA200_ZORUNLU = os.getenv("AL_TEK_HISSE_SMA200_ZORUNLU", "1") != "0"
AL_TEK_HISSE_AY1_MIN = float(os.getenv("AL_TEK_HISSE_AY1_MIN", "-5"))
AL_TEK_HISSE_AY3_MIN = float(os.getenv("AL_TEK_HISSE_AY3_MIN", "0"))
AL_TEK_HISSE_ENDEKS_MIN = float(os.getenv("AL_TEK_HISSE_ENDEKS_MIN", "-3"))
AL_TEK_HISSE_Y1_MIN = float(os.getenv("AL_TEK_HISSE_Y1_MIN", "12"))
AL_TEK_HISSE_Y1_IZLE = float(os.getenv("AL_TEK_HISSE_Y1_IZLE", "10"))

# ETF sektör → makro kategori (rejim puan tablosu anahtarı)
ETF_SEKTOR_KATEGORI: Dict[str, str] = {
    "dunya": "hisse_global",
    "abd": "hisse_global",
    "avrupa": "hisse_global",
    "esg": "hisse_global",
    "teknoloji": "teknoloji",
    "gelisen": "gelisen",
    "tahvil": "tahvil",
    "altin": "emtia",
    "temettu": "hisse_global",
}

# Rejim → ETF kategori → puan (max 30)
REJIM_ETF_KATEGORI_PUAN: Dict[str, Dict[str, float]] = {
    "NOTR": {"hisse_global": 15, "tahvil": 25, "gelisen": 10, "teknoloji": 15, "emtia": 12},
    "RISK_ON": {"hisse_global": 25, "gelisen": 25, "tahvil": 5, "teknoloji": 25, "emtia": 8},
    "ENFLASYON_KORUMA": {"emtia": 28, "tahvil": 5, "hisse_global": 10, "teknoloji": 5, "gelisen": 8},
    "BELIRSIZ": {"hisse_global": 15, "tahvil": 15, "gelisen": 15, "teknoloji": 15, "emtia": 15},
    "TL_FIRSAT": {"hisse_global": 18, "tahvil": 20, "gelisen": 12, "teknoloji": 15, "emtia": 10},
    "EM_STRES": {"tahvil": 22, "emtia": 20, "hisse_global": 8, "gelisen": 5, "teknoloji": 5},
    "KRIZ": {"tahvil": 25, "emtia": 25, "hisse_global": 5, "gelisen": 3, "teknoloji": 3},
}

# Hisse sektör → makro sektör grubu
HISSE_SEKTOR_GRUBU: Dict[str, str] = {
    "defansif": "defansif",
    "tuketim": "defansif",
    "teknoloji": "teknoloji",
    "buyume": "dongusel",
    "sanayi": "dongusel",
    "hava": "dongusel",
    "holding": "dongusel",
    "savunma": "dongusel",
    "enerji": "enerji",
    "finans": "finans",
}

# Rejim → hisse sektör grubu → puan (max 30)
REJIM_HISSE_SEKTOR_PUAN: Dict[str, Dict[str, float]] = {
    "NOTR": {"defansif": 25, "dongusel": 10, "teknoloji": 15, "enerji": 12, "finans": 15},
    "RISK_ON": {"teknoloji": 25, "dongusel": 20, "defansif": 10, "enerji": 15, "finans": 12},
    "ENFLASYON_KORUMA": {"enerji": 25, "finans": 15, "teknoloji": 5, "defansif": 12, "dongusel": 10},
    "BELIRSIZ": {"defansif": 15, "dongusel": 15, "teknoloji": 15, "enerji": 15, "finans": 15},
    "TL_FIRSAT": {"finans": 22, "defansif": 18, "dongusel": 12, "teknoloji": 12, "enerji": 10},
    "EM_STRES": {"defansif": 22, "enerji": 18, "finans": 12, "teknoloji": 5, "dongusel": 8},
    "KRIZ": {"defansif": 25, "enerji": 15, "finans": 10, "teknoloji": 3, "dongusel": 5},
}

# ETF kategori min. yatırım ufku (gün) — profil vadesi bunun altındaysa vade puanı 0
ETF_MIN_UFUK_GUN: Dict[str, int] = {
    "dunya": 181,
    "abd": 181,
    "avrupa": 181,
    "teknoloji": 181,
    "esg": 181,
    "temettu": 181,
    "gelisen": 365,
    "altin": 181,
    "tahvil": 92,
}

# Profil risk → kabul edilebilir yıllık vol (%), 30G gerçekleşen vol ile karşılaştırılır
PROFIL_MAX_VOL_YILLIK: Dict[str, float] = {
    "dusuk": 22.0,
    "orta": 32.0,
    "yuksek": 45.0,
}

# USD bazlı ETF (EUR yatırımcı için kur şoku notu)
USD_BAZLI_ETF_SEKTORLER = frozenset({"abd", "teknoloji"})

# Signal Engine v2 — çok faktörlü sinyal motoru
USE_SIGNAL_ENGINE_V2 = os.getenv("USE_SIGNAL_ENGINE_V2", "1") != "0"


@dataclass
class Esikler:
    """Kod içinde okunabilirlik için eşiklerin nesne hâli."""
    cds_kritik: float = 400.0
    cds_yuksek: float = 300.0
    cds_orta: float = 250.0
