# TL Yatırım Karar Asistanı

Bu proje, sohbette tasarlanan **4 kapılı kural tabanlı algoritmayı** çalışan bir
yazılıma dönüştürür: güncel piyasa verilerini toplar, algoritmayı çalıştırır ve
size (ve isterseniz Telegram'a) bir karar-destek raporu üretir.

**Bu bir alım-satım botu değildir.** Hiçbir işlemi otomatik yapmaz, para
transfer etmez, hesap açmaz. Sadece veri toplar + hesaplar + raporlar. Nihai
kararı her zaman siz verirsiniz. Finansal tavsiye değildir.

## Hızlı başlangıç (2 dakika, internet gerekmez)

```bash
cd tl-yatirim-asistani
pip install -r requirements.txt
python main.py --demo
```

Bu, önceki konuşmada araştırılan yaklaşık Temmuz 2026 verileriyle örnek bir
rapor üretir — gerçek API bağlantısı kurmadan sistemin nasıl çalıştığını
görmenizi sağlar.

## Gerçek verilerle çalıştırma

### 1. API anahtarlarını alın (hepsi ücretsiz)

| Anahtar | Nereden | Süre |
|---|---|---|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | 2 dk, e-posta ile |
| `EVDS_API_KEY` | https://evds3.tcmb.gov.tr (Profilim → API Key) | Ücretsiz, ~5 dk kayıt |
| Telegram bot | `notifier.py` dosyasının başındaki yorumlara bakın | 5 dk |

GDELT (siyasi/savaş risk taraması) ve Frankfurter (döviz kuru) için **anahtar
gerekmez**, otomatik çalışır.

### 2. `.env` dosyasını oluşturun

```bash
cp .env.example .env
# .env dosyasını açıp anahtarlarınızı ve portföy büyüklüğünüzü girin
pip install python-dotenv
```

### 3. CDS değerini elle güncelleyin

Türkiye 5 yıllık CDS için güvenilir, ücretsiz bir açık API bulunmuyor. İlk
çalıştırmada otomatik oluşturulan `manual_inputs.json` dosyasını açıp güncel
değeri şuradan girin:

- worldgovernmentbonds.com/cds/turkey
- Bankanızın günlük piyasa bültenleri (Garanti BBVA Yatırım, İş Yatırım vb.)

```json
{
  "cds_5y_bp": 265,
  "tl_mevduat_brut_faiz": 0.41,
  "guncelleme_tarihi": "2026-07-01"
}
```

Bu dosyayı haftada bir güncellemeniz yeterli.

### 4. Çalıştırın

```bash
python main.py                 # sadece konsola yazdır
python main.py --telegram      # aynı zamanda Telegram'a gönder
```

## Otomatik / zamanlanmış çalıştırma

### Seçenek A — GitHub Actions (önerilen, ücretsiz, bilgisayarınız kapalı olsa da çalışır)

1. Bu klasörü bir GitHub deposuna yükleyin (`git init && git add . && git commit -m "ilk" && ...`)
2. Depo ayarlarında **Settings → Secrets and variables → Actions** bölümüne
   `FRED_API_KEY`, `EVDS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   değerlerini "Secret" olarak ekleyin (`.env` dosyasını asla depoya yüklemeyin).
3. `.github/workflows/gunluk-rapor.yml` dosyası hazır — her gün 09:00'da
   (TR saati) otomatik çalışıp Telegram'a rapor gönderir.
4. `manual_inputs.json` içindeki CDS değerini haftada bir siz güncelleyip
   depoya push etmeniz yeterli (veya ileride bir kaynağa bağlayabilirsiniz).

### Seçenek B — Kendi bilgisayarınızda cron (Mac/Linux)

```bash
crontab -e
# aşağıdaki satırı ekleyin (her gün 09:00'da çalıştırır):
0 9 * * * cd /tam/yol/tl-yatirim-asistani && /usr/bin/python3 main.py --telegram
```

### Mac — sessiz fiyat + analist önbellek (15 dk)

Uygulama kapalıyken bile fiyat (≤15 dk) ve analist cache’i sıcak tutar; Streamlit
açılınca kasılmaz:

```bash
bash macos/cache_refresh_kurulum.sh
# Log: ~/Library/Application Support/TLYatirimAsistani/cache_refresh.log
# Manuel: python main.py --cache-yenile
```

## Dosya yapısı

```
tl-yatirim-asistani/
├── config.py              # tüm eşik değerleri (algoritmayı burada ayarlarsınız)
├── data_sources.py        # dış API'lerden veri çeken fonksiyonlar
├── decision_engine.py     # 4 kapılı karar algoritması (saf mantık, test edilebilir)
├── notifier.py            # rapor metni oluşturma + Telegram gönderimi
├── main.py                # her şeyi birleştiren ana betik
├── manual_inputs.json     # CDS gibi elle girilen veriler (ilk çalıştırmada oluşur)
├── requirements.txt
├── .env.example            # kopyalayıp .env yapın
└── .github/workflows/      # GitHub Actions ile günlük otomatik çalıştırma
```

## Algoritmayı değiştirmek isterseniz

Tüm eşikler (`CDS_ESIK_TABLOSU`, `MUTLAK_TAVAN`, `TRANS_SAYISI`, siyasi risk
anahtar kelimeleri vb.) tek bir yerde: **`config.py`**. Kararın mantığını
değiştirmek isterseniz `decision_engine.py` içindeki `karar_ver()`
fonksiyonuna yeni bir kapı eklemeniz yeterli — her kapı bağımsız bir
adım olarak yazıldığı için mevcut mantığı bozmadan genişletebilirsiniz.

## Sınırlamalar (dürüstçe)

- **CDS** için güvenilir ücretsiz API yok — elle güncellemeniz gerekiyor.
- **Siyasi risk taraması** (GDELT) bir haber-hacmi sayacıdır, gerçek bir
  "anlam analizi" değildir. Kriz eşiğini aştığında bile haberin içeriğini
  siz okuyup teyit etmelisiniz.
- **TCMB politika faizi** için EVDS seri kodunu kendi panelinizden
  doğrulayıp `main.py` içine eklemeniz gerekiyor (kodlar zamanla
  değişebiliyor, bu yüzden sabit yazılmadı).
- Romanya tarafındaki vergi/beyan kurallarını bu yazılım hesaplamaz —
  bunun için bir vergi danışmanına ihtiyacınız olacak.
